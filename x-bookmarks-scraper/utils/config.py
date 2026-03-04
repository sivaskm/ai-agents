"""
Application configuration loaded from environment variables.

Uses Pydantic Settings to provide typed, validated configuration with
sensible defaults. Values can be overridden via .env file or environment
variables. All settings are centralized here to avoid scattered magic strings.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings with environment variable support.

    Attributes:
        x_base_url: Base URL for X (Twitter).
        bookmarks_url: Direct URL to the bookmarks page.
        data_dir: Directory for output data files.
        session_file: Path to the cookie persistence file.
        headless: Whether to run the browser in headless mode.
        scroll_delay: Seconds to wait between scroll actions.
        max_scroll_retries: Max consecutive no-new-tweet scrolls before stopping.
        max_tweets: Maximum tweets to collect (0 = unlimited).
        output_file: Output filename relative to data_dir.
        log_level: Minimum log level for console output.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # URLs
    x_base_url: str = "https://x.com"
    bookmarks_url: str = "https://x.com/i/bookmarks"

    # Storage paths
    data_dir: str = "data"
    session_file: str = "session.json"

    # Browser behavior
    headless: bool = False

    # Scroll tuning
    scroll_delay: float = 2.0
    max_scroll_retries: int = 5

    # Collection limits
    max_tweets: int = 500  # Safety cap per run (0 = unlimited)
    max_scroll_loops: int = 500  # Hard stop for infinite scroll to prevent runaway
    max_runtime_minutes: int = 120  # Safety cap for scraper duration

    # Output
    output_file: str = "bookmarks.json"

    # Logging
    log_level: str = "INFO"

    # State persistence
    state_dir: str = "state"
    incremental_state_file: str = "incremental_state.json"
    historical_state_file: str = "historical_state.json"

    @property
    def output_path(self) -> Path:
        """Full path to the output JSON file."""
        return Path(self.data_dir) / self.output_file

    @property
    def session_path(self) -> Path:
        """Full path to the session cookie file."""
        return Path(self.session_file)


# Singleton instance — import this across the project
settings = Settings()
