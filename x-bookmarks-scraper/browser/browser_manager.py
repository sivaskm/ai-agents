"""
Browser lifecycle management using Playwright.

Provides an async context manager that handles browser startup, page creation,
and clean shutdown. Supports both headless and headed modes via configuration.
Uses a persistent browser context to support cookie-based session management.
"""

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright
from loguru import logger

from utils.config import settings


class BrowserManager:
    """
    Manages the Playwright browser lifecycle as an async context manager.

    Usage:
        async with BrowserManager() as manager:
            page = manager.page
            await page.goto("https://x.com")

    Design decisions:
        - Uses Chromium for best compatibility with X (Twitter).
        - Creates a single browser context and page to mimic real user behavior.
        - Viewport is set to a standard desktop resolution.
        - User-agent is left default (Playwright's Chromium UA) unless stealth is needed.
    """

    def __init__(self, headless: bool | None = None) -> None:
        """
        Args:
            headless: Override headless mode. If None, uses settings.headless.
        """
        self._headless = headless if headless is not None else settings.headless
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def __aenter__(self) -> "BrowserManager":
        """Start Playwright, launch browser, and create a page."""
        logger.info("Starting browser (headless={})", self._headless)

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            args=[
                "--disable-blink-features=AutomationControlled",  # Reduce detection
            ],
        )

        # Create context with realistic viewport and locale
        self._context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        self._page = await self._context.new_page()

        logger.info("Browser started successfully")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Cleanly shut down browser, context, and Playwright."""
        logger.info("Shutting down browser")

        if self._page:
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

        logger.info("Browser shutdown complete")

    @property
    def page(self) -> Page:
        """The active page instance. Raises if used outside context manager."""
        if self._page is None:
            raise RuntimeError("BrowserManager must be used as an async context manager")
        return self._page

    @property
    def context(self) -> BrowserContext:
        """The browser context instance. Needed for cookie management."""
        if self._context is None:
            raise RuntimeError("BrowserManager must be used as an async context manager")
        return self._context
