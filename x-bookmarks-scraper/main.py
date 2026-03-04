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
    uv run python main.py --max-tweets 10           # quick test run
    uv run python main.py --headless                # headless mode
    uv run python main.py --full-scan               # ignore state, scrape everything
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
    max_tweets: int,
    latest_tweet_id: str | None,
) -> tuple[int, str | None]:
    """
    Incremental scroll + click + extract + save loop.

    Processes bookmarks from newest to oldest. Stops when:
    1. A previously processed tweet is encountered (incremental stop)
    2. max_tweets limit is reached
    3. No new tweets visible after max scroll retries

    Args:
        page: The active Playwright page on bookmarks.
        max_tweets: Max tweets to collect (0 = unlimited).
        latest_tweet_id: Last processed tweet ID (from state). None = first run.

    Returns:
        Tuple of (extracted_count, newest_tweet_id_this_run).
    """
    # Load already-saved IDs for dedup within this session
    seen_ids = get_saved_ids(settings.output_path)
    if seen_ids:
        logger.info("📂 {} bookmarks already saved from previous runs", len(seen_ids))

    extracted_count = 0
    newest_tweet_id: str | None = None
    no_new_rounds = 0
    max_no_new_rounds = settings.max_scroll_retries
    round_num = 0
    bookmarks_url = settings.bookmarks_url
    hit_previous = False

    while not hit_previous:
        round_num += 1
        logger.info("─── Round {} ───", round_num)

        # Step 1: Find unseen tweets in current view
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

            await _scroll_page(page)
            continue

        # Reset no-new counter
        no_new_rounds = 0
        logger.info("Found {} new tweets to process", len(new_tweet_links))

        # Step 2: Process each tweet
        for tweet_info in new_tweet_links:
            tweet_id = tweet_info["tweet_id"]

            # ── INCREMENTAL STOP: Have we reached a previously processed tweet? ──
            if is_tweet_already_processed(tweet_id, latest_tweet_id):
                logger.info(
                    "🛑 Hit previously processed tweet ({}) — incremental stop!",
                    tweet_id,
                )
                hit_previous = True
                break

            # Human-like delay between tweet opens (1.5–3s)
            await asyncio.sleep(random.uniform(1.5, 3.0))

            # Navigate to the tweet detail page for full content
            bookmark = await click_tweet_and_extract(page, tweet_info, bookmarks_url)

            if bookmark:
                # Track the newest tweet ID (first one processed = newest)
                if newest_tweet_id is None:
                    newest_tweet_id = tweet_id

                # Save immediately — incremental, crash-safe
                was_new = append_bookmark(bookmark, settings.output_path)
                if was_new:
                    extracted_count += 1
                    seen_ids.add(tweet_id)
            else:
                # Mark as seen even on failure to avoid infinite retries
                seen_ids.add(tweet_id)

            # Check max_tweets cap
            if max_tweets > 0 and extracted_count >= max_tweets:
                logger.info("📊 Reached max tweet limit ({}). Stopping.", max_tweets)
                await page.goto(bookmarks_url, wait_until="domcontentloaded", timeout=30000)
                return extracted_count, newest_tweet_id

        if hit_previous:
            break

        # Step 3: Return to bookmarks and scroll for more
        logger.info("↩ Returning to bookmarks page")
        await page.goto(bookmarks_url, wait_until="domcontentloaded", timeout=30000)

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

    # Load scraper state for incremental mode
    state = load_state()
    latest_tweet_id = None if args.full_scan else state.latest_tweet_id

    logger.info("=" * 60)
    logger.info("X (Twitter) Bookmarks Scraper — Incremental Mode")
    logger.info("=" * 60)
    logger.info("Max tweets: {}", settings.max_tweets)
    logger.info("Headless: {}", settings.headless)
    logger.info("Output: {}", settings.output_path)
    if latest_tweet_id:
        logger.info("Stop marker: tweet_id={} (last run: {})", latest_tweet_id, state.last_run)
    else:
        logger.info("Mode: FULL SCAN (no previous state)")
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
        logger.info("Step 4: Starting incremental bookmark extraction")
        extracted_count, newest_tweet_id = await scrape_bookmarks_loop(
            page, settings.max_tweets, latest_tweet_id,
        )

        # --- Step 5: Update state ---
        if extracted_count > 0:
            updated_state = update_state_after_run(newest_tweet_id, extracted_count)
            logger.info(
                "State updated: latest_tweet_id={}, total={}",
                updated_state.latest_tweet_id,
                updated_state.total_bookmarks_scraped,
            )
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
