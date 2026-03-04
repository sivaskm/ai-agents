"""
Unit tests for the configuration module.

Tests that default values are set correctly and that the settings
object can be constructed without a .env file.
"""

import pytest
from pathlib import Path


class TestConfig:
    """Test suite for the Settings configuration."""

    def test_default_values(self):
        """Settings should have sensible defaults even without .env."""
        # Import fresh to test defaults
        from utils.config import Settings

        # Create instance without env file to test pure defaults
        config = Settings(_env_file=None)
        assert config.x_base_url == "https://x.com"
        assert config.bookmarks_url == "https://x.com/i/bookmarks"
        assert config.data_dir == "data"
        assert config.session_file == "session.json"
        assert config.headless is False
        assert config.scroll_delay == 2.0
        assert config.max_scroll_retries == 5
        assert config.max_tweets == 500
        assert config.output_file == "bookmarks.json"
        assert config.log_level == "INFO"

    def test_output_path_property(self):
        """output_path should combine data_dir and output_file."""
        from utils.config import Settings

        config = Settings(_env_file=None)
        expected = Path("data") / "bookmarks.json"
        assert config.output_path == expected

    def test_session_path_property(self):
        """session_path should return a Path object."""
        from utils.config import Settings

        config = Settings(_env_file=None)
        assert config.session_path == Path("session.json")

    def test_custom_values(self):
        """Settings should accept custom values."""
        from utils.config import Settings

        config = Settings(
            headless=True,
            max_tweets=200,
            scroll_delay=5.0,
            output_file="custom.json",
            log_level="DEBUG",
            _env_file=None,
        )
        assert config.headless is True
        assert config.max_tweets == 200
        assert config.scroll_delay == 5.0
        assert config.output_file == "custom.json"
        assert config.log_level == "DEBUG"
