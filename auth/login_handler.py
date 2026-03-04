"""
Interactive login flow for X (Twitter).

Handles the multi-step login process:
1. Navigate to login page
2. Enter username and click next
3. Enter password and submit
4. Wait for successful redirect

Uses terminal prompts for credentials (getpass for password) to avoid
storing sensitive data in config files. After successful login, the
session is saved via session_manager.
"""

import getpass

from playwright.async_api import BrowserContext, Page
from loguru import logger

from utils.config import settings
from utils.retry import retry
from browser.session_manager import save_session


@retry(max_attempts=2, base_delay=3.0, exceptions=(Exception,))
async def perform_login(page: Page, context: BrowserContext) -> None:
    """
    Execute the full X login flow with terminal-based credential input.

    The X login flow is a multi-step process:
    1. Username field → "Next" button
    2. Password field → "Log in" button
    3. Wait for redirect to home timeline

    Args:
        page: The active Playwright page.
        context: The browser context (needed for session saving).

    Raises:
        Exception: If login fails after all retry attempts.
    """
    logger.info("Starting login flow")

    # Prompt for credentials in terminal
    print("\n" + "=" * 50)
    print("  X (Twitter) Login Required")
    print("=" * 50)
    username = input("  Enter username or email: ").strip()
    password = getpass.getpass("  Enter password: ")
    print("=" * 50 + "\n")

    if not username or not password:
        raise ValueError("Username and password are required")

    # Step 1: Navigate to the login page
    login_url = f"{settings.x_base_url}/i/flow/login"
    logger.info("Navigating to login page: {}", login_url)
    await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)

    # Step 2: Enter username
    logger.info("Entering username")
    username_field = page.locator('input[autocomplete="username"]')
    await username_field.wait_for(state="visible", timeout=15000)
    await username_field.fill(username)

    # Click "Next" button
    next_button = page.locator('button:has-text("Next")')
    await next_button.click()
    logger.info("Username submitted, waiting for password field")

    # Step 3: Wait for and fill password field
    # X sometimes shows an intermediate verification step — handle gracefully
    await page.wait_for_timeout(2000)  # Brief pause for transition

    # Check if there's a phone/email verification step
    unusual_activity = page.locator('input[data-testid="ocfEnterTextTextInput"]')
    try:
        await unusual_activity.wait_for(state="visible", timeout=5000)
        # Verification step detected — prompt user
        logger.warning("X is requesting additional verification")
        print("\n⚠️  X is requesting additional verification.")
        verification_input = input("  Enter the verification text (phone/email): ").strip()
        await unusual_activity.fill(verification_input)
        verify_next = page.locator('button[data-testid="ocfEnterTextNextButton"]')
        await verify_next.click()
        await page.wait_for_timeout(2000)
    except Exception:
        # No verification step — continue to password
        pass

    # Step 4: Enter password
    logger.info("Entering password")
    password_field = page.locator('input[name="password"]')
    await password_field.wait_for(state="visible", timeout=15000)
    await password_field.fill(password)

    # Click "Log in" button
    login_button = page.locator('button[data-testid="LoginForm_Login_Button"]')
    await login_button.click()
    logger.info("Password submitted, waiting for login completion")

    # Step 5: Wait for successful login redirect
    # After login, X typically redirects to the home timeline
    try:
        await page.wait_for_url(
            f"{settings.x_base_url}/home",
            timeout=30000,
        )
        logger.success("Login successful! Redirected to home timeline")
    except Exception:
        # Sometimes X redirects elsewhere — check if we're logged in
        if "home" in page.url or "x.com" in page.url:
            logger.success("Login appears successful (URL: {})", page.url)
        else:
            raise RuntimeError(
                f"Login may have failed. Current URL: {page.url}. "
                "Check credentials and try again."
            )

    # Step 6: Save session for future runs
    await save_session(context)
    logger.info("Login flow completed and session saved")
