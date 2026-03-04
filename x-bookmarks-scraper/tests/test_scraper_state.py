"""
Unit tests for the scraper state module.

Tests state load/save, incremental stop logic, and
state update after run using the ScraperStateManager.
"""

import json
import pytest
from pathlib import Path

from state.scraper_state import ScraperState, ScraperStateManager


class TestScraperState:
    """Test suite for scraper state persistence."""

    def test_default_state(self):
        """Default state should have no latest_tweet_id."""
        state = ScraperState()
        assert state.latest_tweet_id is None
        assert state.last_run is None
        assert state.total_bookmarks_scraped == 0

    def test_manager_save_and_load(self, tmp_path):
        """Saving and loading state should produce identical objects."""
        state_file = tmp_path / "state.json"
        
        # Create initial state
        manager = ScraperStateManager(state_file)
        manager.update_latest_tweet("1234567890")
        manager.save_state(total=42)
        
        # Load in a new manager
        loaded_manager = ScraperStateManager(state_file)
        loaded = loaded_manager.state
        
        assert loaded.latest_tweet_id == "1234567890"
        assert loaded.total_bookmarks_scraped == 42
        assert loaded.last_run is not None

    def test_load_nonexistent(self, tmp_path):
        """Loading from nonexistent file should return default state."""
        state_file = tmp_path / "missing.json"
        manager = ScraperStateManager(state_file)
        assert manager.state.latest_tweet_id is None

    def test_load_corrupt(self, tmp_path):
        """Loading from corrupt file should return default state."""
        state_file = tmp_path / "corrupt.json"
        state_file.write_text("not json{{{", encoding="utf-8")
        manager = ScraperStateManager(state_file)
        assert manager.state.latest_tweet_id is None

    def test_update_state_after_run(self, tmp_path):
        """update_state_after_run should update tweet ID and increment count."""
        state_file = tmp_path / "state.json"
        manager = ScraperStateManager(state_file)

        # First run
        manager.update_latest_tweet("100")
        manager.save_state(total=10)
        assert manager.state.latest_tweet_id == "100"
        assert manager.state.total_bookmarks_scraped == 10

        # Second run
        manager.update_latest_tweet("200")
        manager.save_state(total=5)
        assert manager.state.latest_tweet_id == "200"
        assert manager.state.total_bookmarks_scraped == 15

    def test_is_tweet_already_processed_newer(self, tmp_path):
        """Newer tweet should NOT be marked as processed."""
        state_file = tmp_path / "state.json"
        manager = ScraperStateManager(state_file)
        manager.update_latest_tweet("100")
        
        assert manager.is_tweet_already_processed("200") is False

    def test_is_tweet_already_processed_same(self, tmp_path):
        """Same tweet should be marked as processed."""
        state_file = tmp_path / "state.json"
        manager = ScraperStateManager(state_file)
        manager.update_latest_tweet("100")
        
        assert manager.is_tweet_already_processed("100") is True

    def test_is_tweet_already_processed_older(self, tmp_path):
        """Older tweet should be marked as processed."""
        state_file = tmp_path / "state.json"
        manager = ScraperStateManager(state_file)
        manager.update_latest_tweet("100")
        
        assert manager.is_tweet_already_processed("50") is True

    def test_is_tweet_already_processed_no_state(self, tmp_path):
        """With no previous state, nothing is processed."""
        state_file = tmp_path / "state.json"
        manager = ScraperStateManager(state_file)
        
        assert manager.is_tweet_already_processed("100") is False

    def test_is_tweet_already_processed_real_ids(self, tmp_path):
        """Test with realistic Twitter Snowflake IDs."""
        state_file = tmp_path / "state.json"
        manager = ScraperStateManager(state_file)
        
        older = "1889123456789"
        newer = "1891239123456"
        
        manager.update_latest_tweet(older)
        assert manager.is_tweet_already_processed(newer) is False
        
        manager.update_latest_tweet(newer)
        assert manager.is_tweet_already_processed(older) is True
