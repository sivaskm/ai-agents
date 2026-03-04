"""
X (Twitter) Bookmarks Scraper — Main Entry Point

Orchestrates the full scraping workflow:
1. Initialize browser with optional session
2. Login if needed (with encrypted credential caching)
3. Navigate to bookmarks page
4. Unified scroll + extract loop:
   - Scan visible tweets for unseen ones
   - Click into each tweet for full content
   - Save each bookmark immediately to JSON
   - Return to bookmarks and scroll for more
5. Summary report

Each bookmark is saved incrementally — no data loss on crashes.

Usage:
    uv run python main.py
    uv run python main.py --max-tweets 100
    uv run python main.py --headless --output-file my_bookmarks.json
"""

import argparse
import asyncio
import random
import sys

from loguru import logger

from utils.logger import setup_logger
from utils.config import settings
from browser.browser_manager import BrowserManager
from browser.session_manager import load_session, is_logged_in, save_session
from auth.login_handler import perform_login
from navigation.bookmarks_page import navigate_to_bookmarks
from extractor.tweet_extractor import collect_visible_tweet_links, click_tweet_and_extract
from storage.json_store import append_bookmark, get_saved_ids


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments with sensible defaults from config."""
    parser = argparse.ArgumentParser(
        description="Scrape bookmarks from X (Twitter)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run python main.py\n"
            "  uv run python main.py --max-tweets 200\n"
            "  uv run python main.py --headless --output-file export.json\n"
        ),
    )
    parser.add_argument(
        "--max-tweets",
        type=int,
        default=settings.max_tweets,
        help=f"Maximum tweets to collect, 0=unlimited (default: {settings.max_tweets})",
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
    return parser.parse_args()


async def scrape_bookmarks_loop(page, max_tweets: int) -> int:
    """
    Unified scroll + click + extract + save loop.

    For each batch of visible tweets:
    1. Collect unseen tweet links from visible DOM
    2. Navigate to each tweet's detail page for full content
    3. Save each bookmark immediately to JSON
    4. Return to bookmarks page
    5. Scroll down for more tweets
    6. Stop when no new tweets found or max_tweets reached

    Args:
        page: The active Playwright page on bookmarks.
        max_tweets: Max tweets to collect (0 = unlimited).

    Returns:
        Total number of bookmarks extracted.
    """
    # Load already-saved IDs to support resume across sessions
    seen_ids = get_saved_ids(settings.output_path)
    if seen_ids:
        logger.info("Resuming — {} bookmarks already saved from previous runs", len(seen_ids))

    extracted_count = 0
    no_new_rounds = 0
    max_no_new_rounds = settings.max_scroll_retries
    round_num = 0
    bookmarks_url = settings.bookmarks_url

    while True:
        round_num += 1
        logger.info("─── Round {} ───", round_num)

        # Step 1: Find new unseen tweets in the current view
        new_tweet_links = await collect_visible_tweet_links(page, seen_ids)

        if not new_tweet_links:
            no_new_rounds += 1
            logger.info(
                "No new tweets visible ({}/{} rounds). Scrolling...",
                no_new_rounds,
                max_no_new_rounds,
            )

            if no_new_rounds >= max_no_new_rounds:
                logger.info("No new tweets after {} rounds. All bookmarks collected.", max_no_new_rounds)
                break

            # Scroll down to load more
            await _scroll_page(page)
            continue

        # Reset no-new counter since we found tweets
        no_new_rounds = 0

        logger.info("Found {} new tweets to process", len(new_tweet_links))

        # Step 2: Click into each tweet, extract, and save
        for tweet_info in new_tweet_links:
            tweet_id = tweet_info["tweet_id"]

            # Navigate to the tweet detail page
            bookmark = await click_tweet_and_extract(page, tweet_info, bookmarks_url)

            if bookmark:
                # Save immediately — incremental, crash-safe
                was_new = append_bookmark(bookmark, settings.output_path)
                if was_new:
                    extracted_count += 1
                    seen_ids.add(tweet_id)
            else:
                # Mark as seen even on failure to avoid infinite retries
                seen_ids.add(tweet_id)

            # Check max_tweets limit
            if max_tweets > 0 and extracted_count >= max_tweets:
                logger.info("Reached max tweet limit ({}). Stopping.", max_tweets)
                # Navigate back to bookmarks before returning
                await page.goto(bookmarks_url, wait_until="domcontentloaded", timeout=30000)
                return extracted_count

        # Step 3: Return to bookmarks and scroll for more
        logger.info("Returning to bookmarks page")
        await page.goto(bookmarks_url, wait_until="domcontentloaded", timeout=30000)

        # Wait for tweets to load
        try:
            tweet_locator = page.locator('[data-testid="tweet"]')
            await tweet_locator.first.wait_for(state="visible", timeout=15000)
        except Exception:
            logger.warning("Bookmarks page may have failed to reload")

        # Scroll to previous position (past already-seen tweets)
        await _scroll_page(page)

    return extracted_count


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

    # Human-like delay
    delay = settings.scroll_delay + random.uniform(0.5, 1.5)
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

    logger.info("=" * 60)
    logger.info("X (Twitter) Bookmarks Scraper")
    logger.info("=" * 60)
    logger.info("Max tweets: {}", settings.max_tweets or "unlimited")
    logger.info("Headless: {}", settings.headless)
    logger.info("Output: {}", settings.output_path)
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

        # --- Step 4: Unified scroll + extract loop ---
        logger.info("Step 4: Starting bookmark extraction (click-into-tweet mode)")
        extracted_count = await scrape_bookmarks_loop(page, settings.max_tweets)

        # Save session after successful run
        await save_session(context)

        logger.info("=" * 60)
        logger.success(
            "Done! Extracted {} bookmarks → {}",
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
