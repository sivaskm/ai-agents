import asyncio
import random
import time
from typing import Tuple

from playwright.async_api import Page
from extractor.base_scraper import BaseScraper
from extractor.tweet_extractor import collect_visible_tweet_links, click_tweet_and_extract
from storage.json_store import append_bookmark, get_saved_ids
from state.scraper_state import ScraperStateManager
from utils.logger import logger
from utils.config import settings


class BrowserScraper(BaseScraper):
    """
    Original DOM-based scraper strategy (V6 logic).
    
    Slow but extremely robust fallback method that actually clicks into
    each tweet and extracts data from the rendered HTML/DOM.
    """

    async def scrape(
        self,
        page: Page,
        max_tweets: int,
        mode: str,
        state_manager: ScraperStateManager
    ) -> int:
        """Execute the browser DOM scraping strategy."""
        logger.info(f"🚀 Starting Browser DOM Extraction (Mode: {mode.upper()})")
        
        seen_ids = get_saved_ids(settings.output_path)
        if seen_ids:
            logger.info(f"📂 {len(seen_ids)} bookmarks already saved in output file")

        extracted_count = 0
        no_new_rounds = 0
        round_num = 0
        bookmarks_url = settings.bookmarks_url
        hit_previous_incremental = False
        
        # State tracking for Historical Mode Resume
        resume_marker = state_manager.state.last_processed_tweet_id if mode == "historical" else None
        stop_marker = state_manager.state.latest_tweet_id if mode == "incremental" else None
        
        found_resume_marker = False if resume_marker else True 
        start_time = time.time()

        while not hit_previous_incremental and round_num < settings.max_scroll_loops:
            round_num += 1
            logger.info(f"─── Browser Scroll Loop {round_num} ───")
            
            # Check overall runtime protection
            if (time.time() - start_time) / 60.0 > settings.max_runtime_minutes:
                logger.warning(f"Reached max runtime of {settings.max_runtime_minutes} minutes. Halting scrape.")
                break

            # Step 1: Find unseen tweets in current view
            new_tweet_links = await collect_visible_tweet_links(page, seen_ids)

            if not new_tweet_links:
                no_new_rounds += 1
                if no_new_rounds >= settings.max_scroll_retries:
                    logger.info(f"No new tweets after {settings.max_scroll_retries} rounds. All bookmarks collected.")
                    break
                await self._scroll_page(page)
                continue

            no_new_rounds = 0
            logger.info(f"Found {len(new_tweet_links)} visible tweets to evaluate")

            # Step 2: Process each tweet
            for tweet_info in new_tweet_links:
                tweet_id = tweet_info["tweet_id"]

                # Historical fast-forwarding logic
                if not found_resume_marker:
                    if tweet_id == resume_marker:
                        logger.info(f"▶ Found historical resume marker ({tweet_id}). Beginning extraction.")
                        found_resume_marker = True
                    else:
                        logger.debug(f"Skipping tweet {tweet_id} (hunting for resume marker {resume_marker})")
                    
                    seen_ids.add(tweet_id)
                    continue

                # Incremental Stop logic
                if mode == "incremental" and state_manager.is_tweet_already_processed(tweet_id):
                    logger.info(f"🛑 Hit previously processed tweet ({tweet_id}) — incremental stop!")
                    hit_previous_incremental = True
                    break

                # Human-like delay between tweet opens (2–6s based on limits)
                await asyncio.sleep(random.uniform(2.0, 6.0))

                # Exponential backoff retry logic for extracting
                bookmark = None
                for attempt in range(3):
                    bookmark = await click_tweet_and_extract(page, tweet_info, bookmarks_url)
                    if bookmark:
                        break
                    else:
                        backoff = 2 * (2 ** attempt)
                        logger.warning(f"Extraction failed for {tweet_id}, retrying in {backoff}s (Attempt {attempt+1}/3)")
                        await asyncio.sleep(backoff)

                if bookmark:
                    was_new = append_bookmark(bookmark.model_dump(), settings.output_path)
                    if was_new:
                        extracted_count += 1
                        seen_ids.add(tweet_id)
                        
                        # Sync state directly
                        state_manager.update_latest_tweet(tweet_id)
                        state_manager.save_state(total=extracted_count)
                else:
                    seen_ids.add(tweet_id)

                if max_tweets > 0 and extracted_count >= max_tweets:
                    logger.info(f"📊 Reached max tweet limit ({max_tweets}). Stopping.")
                    await page.goto(bookmarks_url, wait_until="domcontentloaded", timeout=30000)
                    return extracted_count

            if hit_previous_incremental:
                break

            # Step 3: Return to bookmarks and scroll for more
            logger.info("↩ Returning to bookmarks page and triggering next scroll")
            await page.goto(bookmarks_url, wait_until="domcontentloaded", timeout=30000)

            # Wait for tweets to load
            try:
                tweet_locator = page.locator('[data-testid="tweet"]')
                await tweet_locator.first.wait_for(state="visible", timeout=15000)
            except Exception:
                logger.warning("Bookmarks page may have failed to reload")

            # Scroll past already-processed tweets
            await self._scroll_page(page)

        return extracted_count

    async def _scroll_page(self, page: Page) -> None:
        """Scroll the page down with a human-like delay."""
        tweets = page.locator('[data-testid="tweet"]')
        count = await tweets.count()

        if count > 0:
            try:
                await tweets.last.scroll_into_view_if_needed(timeout=5000)
            except Exception:
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
        else:
            await page.evaluate("window.scrollBy(0, window.innerHeight)")

        # Human-like random delay (1.5–3 seconds)
        delay = random.uniform(1.5, 3.0)
        await asyncio.sleep(delay)

        # Extra wait for content to render
        await page.wait_for_timeout(1000)
