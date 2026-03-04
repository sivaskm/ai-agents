"""
Scraper state persistence for incremental runs.

Stores the latest processed tweet ID and timestamp so subsequent runs
only scrape new bookmarks added since the last run. This is the core
of the incremental scraping strategy — the scraper stops scrolling
as soon as it hits a previously processed tweet.

Tweet IDs are Twitter Snowflake IDs (monotonically increasing integers),
so comparing them numerically tells us which tweet is newer.

State file format (state/scraper_state.json):
    {
        "latest_tweet_id": "1889123456789",
        "last_run": "2026-03-04T21:00:00",
        "total_bookmarks_scraped": 150
    }
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from loguru import logger

from utils.config import settings

# Default location for the state file
STATE_DIR = Path(settings.state_dir)
INCREMENTAL_STATE_FILE = STATE_DIR / settings.incremental_state_file
HISTORICAL_STATE_FILE = STATE_DIR / settings.historical_state_file


class ScraperState(BaseModel):
    """
    Persistent state for scraping runs.
    Supports both incremental (daily updates) and historical (deep archive) modes.
    """

    latest_tweet_id: Optional[str] = Field(
        default=None,
        description="Newest tweet ID from the last run (stop marker for incremental)",
    )
    last_processed_tweet_id: Optional[str] = Field(
        default=None,
        description="The last successfully scraped tweet ID (resume marker for historical)",
    )
    last_index: int = Field(
        default=0,
        description="The index position of the last scraped tweet for resume reference",
    )
    mode: str = Field(
        default="incremental",
        description="The mode this state file belongs to (incremental or historical)",
    )
    last_run: Optional[str] = Field(
        default=None,
        description="ISO timestamp of last successful run",
    )
    total_bookmarks_scraped: int = Field(
        default=0,
        description="Cumulative total bookmarks scraped across all runs",
    )


def load_state(state_path: Path = INCREMENTAL_STATE_FILE) -> ScraperState:
    """
    Load scraper state from the JSON file.

    Args:
        state_path: Path to the state file.

    Returns:
        ScraperState object (defaults if file doesn't exist).
    """
    if not state_path.exists():
        logger.info("No previous state found — first run (will scrape all bookmarks)")
        return ScraperState()

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        state = ScraperState(**data)
        logger.info(
            "Loaded state: latest_tweet_id={}, last_run={}, total={}",
            state.latest_tweet_id,
            state.last_run,
            state.total_bookmarks_scraped,
        )
        return state
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to load state ({}). Starting fresh.", exc)
        return ScraperState()


def save_state(
    state: ScraperState,
    state_path: Path = INCREMENTAL_STATE_FILE,
) -> None:
    """
    Save scraper state to the JSON file.

    Args:
        state: The ScraperState to persist.
        state_path: Path to the state file.
    """
    state_path.parent.mkdir(parents=True, exist_ok=True)

    state_path.write_text(
        json.dumps(state.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(
        "State saved: latest_tweet_id={}, total={}",
        state.latest_tweet_id,
        state.total_bookmarks_scraped,
    )


def update_state_after_run(
    tweet_id: Optional[str],
    new_bookmarks_count: int,
    state_path: Path = INCREMENTAL_STATE_FILE,
    mode: str = "incremental"
) -> ScraperState:
    """
    Update the state file after a successful scraping run.

    In incremental mode: Sets latest_tweet_id to the newest tweet found.
    In historical mode: Sets last_processed_tweet_id to the most recent tweet processed.
    
    Args:
        tweet_id: The marker tweet ID (newest for incremental, just-processed for historical).
        new_bookmarks_count: Number of new bookmarks scraped.
        state_path: Path to the state file.
        mode: "incremental" or "historical"

    Returns:
        The updated ScraperState.
    """
    state = load_state(state_path)
    state.mode = mode

    if tweet_id:
        if mode == "incremental":
            state.latest_tweet_id = tweet_id
        else:
            state.last_processed_tweet_id = tweet_id

    state.last_run = datetime.now().isoformat()
    state.total_bookmarks_scraped += new_bookmarks_count

    save_state(state, state_path)
    return state


def is_tweet_already_processed(tweet_id: str, latest_tweet_id: Optional[str]) -> bool:
    """
    Check if a tweet has already been processed in a previous run.

    Uses numeric comparison of Twitter Snowflake IDs — they are
    monotonically increasing, so a lower ID means an older tweet.

    Args:
        tweet_id: The tweet ID to check.
        latest_tweet_id: The latest tweet ID from the previous run.

    Returns:
        True if the tweet was already processed (is older or equal).
    """
    if latest_tweet_id is None:
        # First run — nothing has been processed yet
        return False

    try:
        return int(tweet_id) <= int(latest_tweet_id)
    except ValueError:
        # Non-numeric IDs — fall back to string comparison
        return tweet_id <= latest_tweet_id
