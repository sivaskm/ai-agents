"""
X (Twitter) Bookmarks Scraper — Main Entry Point

Orchestrates the full scraping workflow:
1. Initialize browser with optional session
2. Login if needed (interactive terminal prompts)
3. Navigate to bookmarks page
4. Scroll to load all bookmarks
5. Extract tweet data (text, author, URL, images)
6. Save to JSON with deduplication

Supports CLI arguments for headless mode, max tweets, and output file.

Usage:
    uv run python main.py
    uv run python main.py --max-tweets 100
    uv run python main.py --headless --output-file my_bookmarks.json
"""

import argparse
import asyncio
import sys

from loguru import logger

from utils.logger import setup_logger
from utils.config import settings
from browser.browser_manager import BrowserManager
from browser.session_manager import load_session, is_logged_in, save_session
from auth.login_handler import perform_login
from navigation.bookmarks_page import navigate_to_bookmarks
from navigation.scroll_manager import scroll_to_load_all
from extractor.tweet_extractor import extract_all_bookmarks
from storage.json_store import save_bookmarks


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
            # Check if the session is still valid
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

        # --- Step 4: Scroll to load all bookmarks ---
        logger.info("Step 4: Scrolling to load bookmarks")
        total_on_page = await scroll_to_load_all(
            page,
            max_tweets=settings.max_tweets,
        )

        # --- Step 5: Extract bookmark data ---
        logger.info("Step 5: Extracting bookmark data")
        seen_ids: set[str] = set()
        bookmarks = await extract_all_bookmarks(page, seen_ids, max_tweets=settings.max_tweets)

        if not bookmarks:
            logger.warning("No bookmarks were extracted. The page may be empty or selectors may have changed.")
            return

        # --- Step 6: Save to JSON ---
        logger.info("Step 6: Saving bookmarks to JSON")
        save_bookmarks(bookmarks, settings.output_path)

        # Save session after successful run
        await save_session(context)

        logger.info("=" * 60)
        logger.success(
            "Done! Extracted {} bookmarks → {}",
            len(bookmarks),
            settings.output_path,
        )
        logger.info("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Scraper interrupted by user")
        sys.exit(0)
    except Exception as exc:
        logger.error("Scraper failed: {}", exc)
        sys.exit(1)
