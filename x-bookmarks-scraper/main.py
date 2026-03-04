"""
X (Twitter) Bookmarks Scraper — Main Entry Point

Implements a strategy-based scraping system:
1. Load scraper state (latest_tweet_id from last run)
2. Open bookmarks page
3. Select scraping strategy (Browser DOM vs GraphQL API)
4. Execute extraction and save incrementally
5. Update state

Usage:
    uv run python main.py                          # incremental scrape (default auto strategy)
    uv run python main.py --mode historical        # historical mode
    uv run python main.py --strategy graphql       # force GraphQL API approach
    uv run python main.py --strategy browser       # force Browser DOM approach
    uv run python main.py --max-tweets 10          # quick test run
    uv run python main.py --headless               # headless mode
"""

import argparse
import asyncio
import sys
from pathlib import Path

from loguru import logger

from utils.logger import setup_logger
from utils.config import settings
from browser.browser_manager import BrowserManager
from browser.session_manager import load_session, is_logged_in, save_session
from auth.login_handler import perform_login
from navigation.bookmarks_page import navigate_to_bookmarks
from extractor.scraper_factory import ScraperFactory
from state.scraper_state import ScraperStateManager


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments with sensible defaults from config."""
    parser = argparse.ArgumentParser(
        description="Scrape bookmarks from X (Twitter) using Strategy pattern",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run python main.py                   # daily incremental run\n"
            "  uv run python main.py --strategy graphql # fast API mode\n"
            "  uv run python main.py --mode historical  # downlaod everything\n"
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
        "--strategy",
        type=str,
        choices=["auto", "graphql", "browser"],
        default="auto",
        help="Extraction strategy (default: auto)",
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
    strategy = args.strategy

    # Load scraper state manager
    if mode == "historical":
        state_file = Path(settings.state_dir) / settings.historical_state_file
    else:
        state_file = Path(settings.state_dir) / settings.incremental_state_file

    # If full-scan, we temporarily clear the markers
    state_manager = ScraperStateManager(state_file)
    if args.full_scan:
        logger.warning("FULL SCAN requested. Ignoring previous state markers.")
        if mode == "incremental":
            state_manager.state.latest_tweet_id = None
        else:
            state_manager.state.last_processed_tweet_id = None

    logger.info("=" * 60)
    logger.info("X (Twitter) Bookmarks Scraper")
    logger.info("=" * 60)
    logger.info(f"Mode:     {mode.upper()}")
    logger.info(f"Strategy: {strategy.upper()}")
    logger.info(f"Max:      {settings.max_tweets}")
    logger.info(f"Headless: {settings.headless}")
    logger.info(f"Output:   {settings.output_path}")
    
    if mode == "incremental":
        if state_manager.state.latest_tweet_id:
            logger.info(f"Stop marker (incremental): {state_manager.state.latest_tweet_id} (last run: {state_manager.state.last_run})")
        else:
            logger.info("Incremental Mode: FULL SCAN (no previous state found)")
    else:
        if state_manager.state.last_processed_tweet_id:
            logger.info(f"Resume marker (historical): {state_manager.state.last_processed_tweet_id} (last index: {state_manager.state.last_index})")
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

        # --- Step 4: Extraction Strategy ---
        logger.info(f"Step 4: Executing {strategy.upper()} extraction strategy")
        operating_max = 0 if args.full_scan else settings.max_tweets
        
        # Instantiate correct scraper
        scraper = ScraperFactory.create(strategy)
        
        extracted_count = await scraper.scrape(
            page=page,
            max_tweets=operating_max,
            mode=mode,
            state_manager=state_manager
        )

        # --- Step 5: Synchronization ---
        if extracted_count > 0:
            logger.info(f"Session finished: total {extracted_count} new bookmarks extracted")
            
            # Feature 8: State Reset After Historical Run
            # If historical mode finished gathering all bookmarks and hit the end of the line,
            # we should update the incremental state so the daily cron job starts from the top.
            if mode == "historical" and state_manager.state.latest_tweet_id:
                inc_state_file = Path(settings.state_dir) / settings.incremental_state_file
                inc_manager = ScraperStateManager(inc_state_file)
                inc_manager.update_latest_tweet(state_manager.state.latest_tweet_id)
                inc_manager.save_state(total=0)
                logger.info(f"Synced historical newest tweet ID ({state_manager.state.latest_tweet_id}) into incremental state.")
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
        # Fix for Windows asyncio ProactorEventLoop errors
        if sys.platform == "win32":
            loop = asyncio.ProactorEventLoop()
            try:
                loop.run_until_complete(main())
            finally:
                loop.close()
        else:
            asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Scraper interrupted by user (data saved incrementally)")
        sys.exit(0)
    except Exception as exc:
        logger.error(f"Scraper failed: {exc}")
        sys.exit(1)
