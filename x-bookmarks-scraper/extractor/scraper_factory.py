from typing import Dict

from playwright.async_api import Page
from extractor.base_scraper import BaseScraper
from extractor.browser_scraper import BrowserScraper
from extractor.graphql_scraper import GraphQLScraper
from state.scraper_state import ScraperStateManager
from utils.logger import logger


class AutoScraper(BaseScraper):
    """
    Smart scraper that attempts the fast GraphQL approach first,
    and seamlessly falls back to the robust Browser approach if it fails.
    """

    async def scrape(
        self,
        page: Page,
        max_tweets: int,
        mode: str,
        state_manager: ScraperStateManager
    ) -> int:
        
        logger.info("🤖 Starting AutoScraper: Attempting GraphQL API first...")
        
        try:
            # Try the fast API approach
            graphql_scraper = GraphQLScraper()
            return await graphql_scraper.scrape(page, max_tweets, mode, state_manager)
            
        except Exception as e:
            logger.error(f"GraphQL Scraper failed unexpectedly: {e}")
            logger.warning("Falling back to Browser DOM Scraper...")
            
            # The page might be in a weird state; reload bookmarks
            try:
                await page.goto("https://x.com/i/bookmarks", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)
            except Exception:
                pass
                
            # Fallback to robust DOM approach
            browser_scraper = BrowserScraper()
            return await browser_scraper.scrape(page, max_tweets, mode, state_manager)


class ScraperFactory:
    """Factory to instantiate the correct scraping strategy based on configuration."""

    _SCRAPERS = {
        "browser": BrowserScraper,
        "graphql": GraphQLScraper,
        "auto": AutoScraper,
    }

    @classmethod
    def create(cls, strategy: str) -> BaseScraper:
        """
        Create a scraper instance based on the strategy name.
        
        Args:
            strategy: "browser", "graphql", or "auto"
            
        Returns:
            An instantiated object implementing BaseScraper.
        """
        strategy_lower = strategy.lower()
        if strategy_lower not in cls._SCRAPERS:
            logger.warning(f"Unknown strategy '{strategy}'. Defaulting to 'auto'.")
            strategy_lower = "auto"
            
        scraper_class = cls._SCRAPERS[strategy_lower]
        return scraper_class()
