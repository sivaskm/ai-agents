"""
Bookmarks page navigation.

Handles navigating to the X bookmarks page and waiting for tweet elements
to load. Uses retry logic for resilient page loading.
"""

from playwright.async_api import Page
from loguru import logger

from utils.config import settings
from utils.retry import retry


@retry(max_attempts=3, base_delay=2.0, exceptions=(Exception,))
async def navigate_to_bookmarks(page: Page) -> None:
    """
    Navigate to the X bookmarks page and wait for tweets to appear.

    Args:
        page: The active Playwright page.

    Raises:
        Exception: If the bookmarks page fails to load after retries.
    """
    logger.info("Navigating to bookmarks: {}", settings.bookmarks_url)
    await page.goto(settings.bookmarks_url, wait_until="domcontentloaded", timeout=30000)

    # Wait for the first tweet to appear — confirms page loaded correctly
    tweet_locator = page.locator('[data-testid="tweet"]')
    await tweet_locator.first.wait_for(state="visible", timeout=20000)

    tweet_count = await tweet_locator.count()
    logger.info("Bookmarks page loaded with {} initial tweets", tweet_count)
