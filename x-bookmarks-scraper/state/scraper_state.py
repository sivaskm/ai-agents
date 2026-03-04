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


class ScraperStateManager:
    """Manages reading and writing the persistent scraper state file."""

    def __init__(self, state_path: Path):
        self.state_path = state_path
        self.state = self._load_state()

    def _load_state(self) -> ScraperState:
        """Load scraper state from the JSON file."""
        if not self.state_path.exists():
            logger.info("No previous state found — first run (will scrape all bookmarks)")
            return ScraperState()

        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            state = ScraperState(**data)
            logger.info(
                "Loaded state: latest_tweet={}, last_run={}, total={}",
                state.latest_tweet_id or state.last_processed_tweet_id,
                state.last_run,
                state.total_bookmarks_scraped,
            )
            return state
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(f"Failed to load state ({exc}). Starting fresh.")
            return ScraperState()

    def save_state(self, total: int = 0) -> None:
        """Save the current state to the JSON file."""
        self.state.total_bookmarks_scraped += total
        self.state.last_run = datetime.now().isoformat()
        
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(self.state.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(
            "State saved: latest_tweet={}, total={}",
            self.state.latest_tweet_id or self.state.last_processed_tweet_id,
            self.state.total_bookmarks_scraped,
        )

    def update_latest_tweet(self, tweet_id: str) -> None:
        """Update the latest/last-processed tweet marker based on mode."""
        if self.state.mode == "incremental":
            self.state.latest_tweet_id = tweet_id
        else:
            self.state.last_processed_tweet_id = tweet_id

    def is_tweet_already_processed(self, tweet_id: str) -> bool:
        """
        Check if a tweet ID is older than or equal to the incremental stop marker.
        Uses numeric comparison of Twitter Snowflake IDs.
        """
        target = self.state.latest_tweet_id
        if target is None:
            return False

        try:
            return int(tweet_id) <= int(target)
        except ValueError:
            return tweet_id <= target
