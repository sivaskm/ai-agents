import asyncio
import json
from typing import List, Optional

from playwright.async_api import Page, Response
from extractor.base_scraper import BaseScraper
from extractor.graphql_parser import parse_bookmarks_response
from storage.json_store import append_bookmark
from state.scraper_state import ScraperStateManager
from utils.logger import logger
from utils.config import settings


class GraphQLScraper(BaseScraper):
    """
    Scraper that intercepts X's internal GraphQL API responses.
    
    Instead of scraping the DOM (which is slow and fragile), this scraper
    listens to the network traffic while the page scrolls natively, grabs the
    JSON payloads that populate the bookmarks, and parses them directly.
    """

    def __init__(self):
        self.captured_responses: asyncio.Queue = asyncio.Queue()
        self.is_listening = False

    async def _on_response(self, response: Response):
        """Playwright callback for all network responses."""
        if not self.is_listening:
            return

        url = response.url
        if "/i/api/graphql/" in url and "Bookmarks" in url:
            try:
                # Ensure the response is OK before trying to parse JSON
                if response.status == 200:
                    body = await response.json()
                    await self.captured_responses.put(body)
                    logger.debug(f"Intercepted GraphQL Bookmarks payload ({len(json.dumps(body))} bytes)")
            except Exception as e:
                logger.debug(f"Failed to read intercepted GraphQL response: {e}")

    async def scrape(
        self,
        page: Page,
        max_tweets: int,
        mode: str,
        state_manager: ScraperStateManager
    ) -> int:
        """
        Execute the GraphQL API interception strategy.
        """
        logger.info(f"🚀 Starting GraphQL API Extraction (Mode: {mode.upper()})")
        extracted_count = 0
        total_scraped = 0
        
        # 1. Attach the network listener
        self.is_listening = True
        page.on("response", self._on_response)

        try:
            # 2. Trigger initial load / scroll loop
            # The page is already on /i/bookmarks from main.py, so the first API call
            # either just happened or is happening. We will scroll to force more.
            max_scrolls = 200
            empty_rounds = 0

            for scroll_round in range(1, max_scrolls + 1):
                logger.info(f"─── API Scroll Round {scroll_round} ───")
                
                # Wait for any pending intercepted payloads (up to 5 seconds)
                new_bookmarks = []
                try:
                    # Collect all payloads currently in the queue
                    while True:
                        payload = await asyncio.wait_for(self.captured_responses.get(), timeout=3.0)
                        bms, _ = parse_bookmarks_response(payload)
                        new_bookmarks.extend(bms)
                        
                except asyncio.TimeoutError:
                    # Timeout means no new payloads arrived in the last 3s
                    pass

                if new_bookmarks:
                    empty_rounds = 0
                    logger.success(f"Successfully parsed {len(new_bookmarks)} bookmarks from API")
                    
                    for bookmark in new_bookmarks:
                        # Check limits
                        if max_tweets > 0 and extracted_count >= max_tweets:
                            logger.info(f"Reached max limit of {max_tweets} tweets.")
                            return extracted_count

                        # Check if already processed (for incremental mode)
                        tweet_id = bookmark.tweet_id
                        total_scraped += 1
                        
                        if state_manager.is_tweet_already_processed(tweet_id):
                            if mode == "incremental":
                                logger.info(f"🛑 Reached previously scraped tweet [{tweet_id}]. Incremental run complete.")
                                return extracted_count
                            else:
                                continue  # In historical mode, just skip duplicates and keep digging

                        # Save bookmark
                        append_bookmark(bookmark.model_dump(), settings.output_path)
                        extracted_count += 1
                        
                        # Sync state for resilience
                        state_manager.update_latest_tweet(tweet_id)
                        state_manager.save_state(total=extracted_count)
                        
                        logger.info(f"💾 Saved API bookmark #{extracted_count}: @{bookmark.author} — {bookmark.text[:50]}...")
                
                else:
                    empty_rounds += 1
                    logger.warning(f"No new payloads intercepted this round ({empty_rounds}/3 empty rounds)")
                    if empty_rounds >= 3:
                        logger.info("Reached end of bookmarks (API empty 3 times).")
                        break

                # Force the browser to request the next page by fast-scrolling
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                # A small delay to let the browser process the scroll and fire the XHR
                await asyncio.sleep(2.0)

        finally:
            # Clean up listener
            self.is_listening = False
            page.remove_listener("response", self._on_response)
            
        return extracted_count
