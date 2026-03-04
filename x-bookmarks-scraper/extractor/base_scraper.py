from abc import ABC, abstractmethod
from typing import Optional

from playwright.async_api import Page
from state.scraper_state import ScraperStateManager


class BaseScraper(ABC):
    """
    Abstract base class defining the interface for all bookmark scrapers.
    
    This strategy pattern allows dynamically switching between:
    - Browser DOM Scraping (robust but slow)
    - GraphQL API Interception (very fast)
    """

    @abstractmethod
    async def scrape(
        self,
        page: Page,
        max_tweets: int,
        mode: str,
        state_manager: ScraperStateManager
    ) -> int:
        """
        Execute the scraping strategy.

        Args:
            page: The active Playwright page (already logged in and on bookmarks).
            max_tweets: Maximum number of bookmarks to parse.
            mode: "historical" or "incremental".
            state_manager: Manager handling checkpoints and resume state.

        Returns:
            int: The total number of new bookmarks successfully extracted and saved.
        """
        pass
