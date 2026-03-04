"""
Unit tests for the scraper state module.

Tests state load/save, incremental stop logic, and
state update after run.
"""

import json
import pytest
from pathlib import Path

from state.scraper_state import (
    ScraperState,
    load_state,
    save_state,
    update_state_after_run,
    is_tweet_already_processed,
)


class TestScraperState:
    """Test suite for scraper state persistence."""

    def test_default_state(self):
        """Default state should have no latest_tweet_id."""
        state = ScraperState()
        assert state.latest_tweet_id is None
        assert state.last_run is None
        assert state.total_bookmarks_scraped == 0

    def test_save_and_load(self, tmp_path):
        """Saving and loading state should produce identical objects."""
        state_file = tmp_path / "state.json"
        state = ScraperState(
            latest_tweet_id="1234567890",
            last_run="2026-03-04T21:00:00",
            total_bookmarks_scraped=42,
        )
        save_state(state, state_file)

        loaded = load_state(state_file)
        assert loaded.latest_tweet_id == "1234567890"
        assert loaded.last_run == "2026-03-04T21:00:00"
        assert loaded.total_bookmarks_scraped == 42

    def test_load_nonexistent(self, tmp_path):
        """Loading from nonexistent file should return default state."""
        state_file = tmp_path / "missing.json"
        state = load_state(state_file)
        assert state.latest_tweet_id is None

    def test_load_corrupt(self, tmp_path):
        """Loading from corrupt file should return default state."""
        state_file = tmp_path / "corrupt.json"
        state_file.write_text("not json{{{", encoding="utf-8")
        state = load_state(state_file)
        assert state.latest_tweet_id is None

    def test_update_state_after_run(self, tmp_path):
        """update_state_after_run should update tweet ID and increment count."""
        state_file = tmp_path / "state.json"

        # First run
        state = update_state_after_run("100", 10, state_file)
        assert state.latest_tweet_id == "100"
        assert state.total_bookmarks_scraped == 10
        assert state.last_run is not None

        # Second run
        state = update_state_after_run("200", 5, state_file)
        assert state.latest_tweet_id == "200"
        assert state.total_bookmarks_scraped == 15

    def test_is_tweet_already_processed_newer(self):
        """Newer tweet should NOT be marked as processed."""
        assert is_tweet_already_processed("200", "100") is False

    def test_is_tweet_already_processed_same(self):
        """Same tweet should be marked as processed."""
        assert is_tweet_already_processed("100", "100") is True

    def test_is_tweet_already_processed_older(self):
        """Older tweet should be marked as processed."""
        assert is_tweet_already_processed("50", "100") is True

    def test_is_tweet_already_processed_no_state(self):
        """With no previous state, nothing is processed."""
        assert is_tweet_already_processed("100", None) is False

    def test_is_tweet_already_processed_real_ids(self):
        """Test with realistic Twitter Snowflake IDs."""
        older = "1889123456789"
        newer = "1891239123456"
        assert is_tweet_already_processed(newer, older) is False
        assert is_tweet_already_processed(older, newer) is True
