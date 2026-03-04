"""
X (Twitter) Bookmarks Scraper — Main Entry Point

Implements an incremental scraping strategy:
1. Load scraper state (latest_tweet_id from last run)
2. Open bookmarks, scan visible tweets
3. For each new tweet: click into detail page → extract full content → save immediately
4. STOP when we hit a previously processed tweet (incremental stop)
5. Update scraper state with the newest tweet ID

This means daily runs only process new bookmarks — typically 5–30 seconds
instead of scrolling through the entire history.

Usage:
    uv run python main.py                          # incremental scrape (default 500 cap)
    uv run python main.py --mode historical         # historical mode
    uv run python main.py --max-tweets 10           # quick test run
    uv run python main.py --headless                # headless mode
    uv run python main.py --full-scan               # ignore state, scrape everything
"""

import argparse
import asyncio
import random
import sys
import time

from loguru import logger

from utils.logger import setup_logger
from utils.config import settings
from browser.browser_manager import BrowserManager
from browser.session_manager import load_session, is_logged_in, save_session
from auth.login_handler import perform_login
from navigation.bookmarks_page import navigate_to_bookmarks
from extractor.tweet_extractor import collect_visible_tweet_links, click_tweet_and_extract
from storage.json_store import append_bookmark, get_saved_ids
from state.scraper_state import (
    load_state,
    update_state_after_run,
    is_tweet_already_processed,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments with sensible defaults from config."""
    parser = argparse.ArgumentParser(
        description="Scrape bookmarks from X (Twitter) — incremental mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run python main.py                   # daily incremental run\n"
            "  uv run python main.py --max-tweets 10    # quick test\n"
            "  uv run python main.py --full-scan        # ignore state, scrape all\n"
            "  uv run python main.py --headless         # background mode\n"
        ),
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["incremental", "historical"],
        default="incremental",
        help="Scraping mode: 'incremental' (only new) or 'historical' (all available)",
    )
    parser.add_argument(
        "--max-tweets",
        type=int,
        default=settings.max_tweets,
        help=f"Maximum tweets to collect per run (default: {settings.max_tweets})",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=settings.headless,
        help="Run browser in headless mode",
    )
    parser.add_argument(
        "--output-file",
        type=str,
        default=settings.output_file,
        help=f"Output JSON filename (default: {settings.output_file})",
    )
    parser.add_argument(
        "--full-scan",
        action="store_true",
        default=False,
        help="Ignore previous state and scrape all bookmarks",
    )
    return parser.parse_args()


async def scrape_bookmarks_loop(
    page,
    mode: str,
    max_tweets: int,
    stop_marker: str | None,
    resume_marker: str | None,
) -> tuple[int, str | None]:
    """
    Incremental scroll + click + extract + save loop.

    In incremental mode: Stops when hitting the stop_marker.
    In historical mode: Fast forwards past the resume_marker then extracts everyone.
    """
    seen_ids = get_saved_ids(settings.output_path)
    if seen_ids:
        logger.info("📂 {} bookmarks already saved in output file", len(seen_ids))

    extracted_count = 0
    newest_tweet_id: str | None = None
    no_new_rounds = 0
    round_num = 0
    bookmarks_url = settings.bookmarks_url
    hit_previous_incremental = False
    
    # State tracking for Historical Mode Resume
    found_resume_marker = False if resume_marker else True 
    start_time = time.time()

    while not hit_previous_incremental and round_num < settings.max_scroll_loops:
        round_num += 1
        logger.info("─── Scroll Loop {} ───", round_num)
        
        # Check overall runtime protection
        if (time.time() - start_time) / 60.0 > settings.max_runtime_minutes:
            logger.warning("Reached max runtime of {} minutes. Halting scrape.", settings.max_runtime_minutes)
            break

        # Step 1: Find unseen tweets in current view
        new_tweet_links = await collect_visible_tweet_links(page, seen_ids)

        if not new_tweet_links:
            no_new_rounds += 1
            if no_new_rounds >= settings.max_scroll_retries:
                logger.info("No new tweets after {} rounds. All bookmarks collected.", settings.max_scroll_retries)
                break
            await _scroll_page(page)
            continue

        no_new_rounds = 0
        logger.info("Found {} visible tweets to evaluate", len(new_tweet_links))

        # Step 2: Process each tweet
        for tweet_info in new_tweet_links:
            tweet_id = tweet_info["tweet_id"]

            # Historical fast-forwarding logic
            if not found_resume_marker:
                if tweet_id == resume_marker:
                    logger.info("▶ Found historical resume marker ({}). Beginning extraction.", tweet_id)
                    found_resume_marker = True
                else:
                    logger.debug("Skipping tweet {} (hunting for resume marker {})", tweet_id, resume_marker)
                
                # We always add it to seen_ids so we don't accidentally evaluate it again while scrolling
                seen_ids.add(tweet_id)
                continue

            # Incremental Stop logic
            if mode == "incremental" and is_tweet_already_processed(tweet_id, stop_marker):
                logger.info("🛑 Hit previously processed tweet ({}) — incremental stop!", tweet_id)
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
                    logger.warning("Extraction failed for {}, retrying in {}s (Attempt {}/3)", tweet_id, backoff, attempt+1)
                    await asyncio.sleep(backoff)

            if bookmark:
                if newest_tweet_id is None:
                    newest_tweet_id = tweet_id

                was_new = append_bookmark(bookmark, settings.output_path)
                if was_new:
                    extracted_count += 1
                    seen_ids.add(tweet_id)
                    
                    # FEATURE 2: Checkpoint/Resume System (Save state after each processed bookmark)
                    state_file = Path(settings.state_dir) / (
                        settings.historical_state_file if mode == "historical" else settings.incremental_state_file
                    )
                    # We pass the CURRENT tweet_id to be stored as the latest successful scrape
                    update_state_after_run(tweet_id, 1, state_path=state_file, mode=mode)
            else:
                seen_ids.add(tweet_id)

            if max_tweets > 0 and extracted_count >= max_tweets:
                logger.info("📊 Reached max tweet limit ({}). Stopping.", max_tweets)
                await page.goto(bookmarks_url, wait_until="networkidle", timeout=30000)
                return extracted_count, newest_tweet_id

        if hit_previous_incremental:
            break

        # Step 3: Return to bookmarks and scroll for more
        logger.info("↩ Returning to bookmarks page and triggering next scroll")
        await page.goto(bookmarks_url, wait_until="networkidle", timeout=30000)

        # Wait for tweets to load
        try:
            tweet_locator = page.locator('[data-testid="tweet"]')
            await tweet_locator.first.wait_for(state="visible", timeout=15000)
        except Exception:
            logger.warning("Bookmarks page may have failed to reload")

        # Scroll past already-processed tweets
        await _scroll_page(page)

    return extracted_count, newest_tweet_id


async def _scroll_page(page) -> None:
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


async def main() -> None:
    """Main orchestration coroutine for the bookmarks scraper."""
    args = parse_args()

    # Override settings from CLI args
    settings.max_tweets = args.max_tweets
    settings.headless = args.headless
    settings.output_file = args.output_file

    # Initialize logging
    setup_logger(log_level=settings.log_level)

    mode = args.mode

    # Load scraper state based on mode
    if mode == "historical":
        state_file = Path(settings.state_dir) / settings.historical_state_file
    else:
        state_file = Path(settings.state_dir) / settings.incremental_state_file

    state = load_state(state_file)
    
    # In incremental mode, we stop at latest_tweet_id
    # In historical mode, we resume from last_processed_tweet_id (set to None if full-scan)
    if mode == "incremental":
        stop_marker = None if args.full_scan else state.latest_tweet_id
        resume_marker = None
    else:
        stop_marker = None
        resume_marker = None if args.full_scan else state.last_processed_tweet_id

    logger.info("=" * 60)
    logger.info("X (Twitter) Bookmarks Scraper — Mode: {}", mode.upper())
    logger.info("=" * 60)
    logger.info("Max tweets: {}", settings.max_tweets)
    logger.info("Headless: {}", settings.headless)
    logger.info("Output: {}", settings.output_path)
    
    if mode == "incremental":
        if stop_marker:
            logger.info("Stop marker (incremental): tweet_id={} (last run: {})", stop_marker, state.last_run)
        else:
            logger.info("Incremental Mode: FULL SCAN (no previous state found)")
    else:
        if resume_marker:
            logger.info("Resume marker (historical): tweet_id={} (last index: {})", resume_marker, state.last_index)
        else:
            logger.info("Historical Mode: FULL DEEP SCAN (starting from newest)")
            
    logger.info("=" * 60)

    async with BrowserManager(headless=settings.headless) as browser:
        page = browser.page
        context = browser.context

        # --- Step 1: Session Management ---
        logger.info("Step 1: Loading session")
        session_loaded = await load_session(context)

        if session_loaded:
            logger.info("Session found. Verifying login state...")
            logged_in = await is_logged_in(page)
        else:
            logged_in = False

        # --- Step 2: Login if needed ---
        if not logged_in:
            logger.info("Step 2: Login required")
            await perform_login(page, context)
        else:
            logger.info("Step 2: Already logged in — skipping login")

        # --- Step 3: Navigate to bookmarks ---
        logger.info("Step 3: Navigating to bookmarks")
        await navigate_to_bookmarks(page)

        # --- Step 4: Incremental scroll + extract loop ---
        logger.info("Step 4: Starting bookmark extraction loop")
        # Support full-scan via args overriding safety bounds temporarily
        operating_max = 0 if args.full_scan else settings.max_tweets
        
        extracted_count, newest_tweet_id = await scrape_bookmarks_loop(
            page, 
            mode,
            operating_max, 
            stop_marker,
            resume_marker
        )

        # --- Step 5: Synchronization ---
        if extracted_count > 0:
            logger.info("Session finished: total {} new bookmarks extracted", extracted_count)
            
            # Feature 8: State Reset After Historical Run
            # If historical mode finished gathering all bookmarks and hit the end of the line (or stopped gracefully),
            # we should update the incremental state so the daily cron job doesn't try to scrape everything.
            if mode == "historical" and newest_tweet_id:
                inc_state_file = Path(settings.state_dir) / settings.incremental_state_file
                update_state_after_run(newest_tweet_id, 0, state_path=inc_state_file, mode="incremental")
                logger.info("Synced historical newest tweet ID ({}) into incremental state.", newest_tweet_id)
        else:
            logger.info("No new bookmarks found — state unchanged")

        # Save session after successful run
        await save_session(context)

        logger.info("=" * 60)
        logger.success(
            "Done! Extracted {} new bookmarks → {}",
            extracted_count,
            settings.output_path,
        )
        logger.info("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Scraper interrupted by user (data saved incrementally)")
        sys.exit(0)
    except Exception as exc:
        logger.error("Scraper failed: {}", exc)
        sys.exit(1)
