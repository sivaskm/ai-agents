"""
Session persistence via cookie management.

Saves and loads browser cookies to/from a JSON file so users don't need
to re-login every time the scraper runs. Also provides login-state detection
by checking for known logged-in DOM elements.
"""

import json
from pathlib import Path
from typing import List, Dict, Any

from playwright.async_api import BrowserContext, Page
from loguru import logger

from utils.config import settings
from utils.retry import retry


async def save_session(context: BrowserContext, session_path: Path | None = None) -> None:
    """
    Save browser cookies to a JSON file.

    Args:
        context: The Playwright browser context to extract cookies from.
        session_path: Path to save session file. Defaults to settings.session_path.
    """
    path = session_path or settings.session_path
    cookies = await context.cookies()

    path.write_text(
        json.dumps(cookies, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Session saved ({} cookies) to {}", len(cookies), path)


async def load_session(context: BrowserContext, session_path: Path | None = None) -> bool:
    """
    Load cookies from a JSON file into the browser context.

    Args:
        context: The Playwright browser context to load cookies into.
        session_path: Path to the session file. Defaults to settings.session_path.

    Returns:
        True if session was loaded successfully, False otherwise.
    """
    path = session_path or settings.session_path

    if not path.exists():
        logger.info("No session file found at {}", path)
        return False

    try:
        cookies: List[Dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        await context.add_cookies(cookies)
        logger.info("Session loaded ({} cookies) from {}", len(cookies), path)
        return True
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to load session ({}). Will require fresh login.", exc)
        return False


@retry(max_attempts=2, base_delay=2.0, exceptions=(Exception,))
async def is_logged_in(page: Page) -> bool:
    """
    Detect whether the user is currently logged in to X.

    Checks for the presence of navigation elements that only appear when
    authenticated (e.g., the home timeline link or the account menu).

    Args:
        page: The active Playwright page.

    Returns:
        True if the user appears to be logged in.
    """
    try:
        # Navigate to X home if not already there
        if "x.com" not in page.url:
            await page.goto(settings.x_base_url, wait_until="domcontentloaded", timeout=30000)

        # Check for authenticated-only elements
        # The account switcher / profile menu is a reliable indicator
        account_menu = page.locator('[data-testid="SideNav_AccountSwitcher_Button"]')
        await account_menu.wait_for(state="visible", timeout=10000)
        logger.info("User is logged in (account menu detected)")
        return True
    except Exception:
        logger.info("User is not logged in (no account menu found)")
        return False
