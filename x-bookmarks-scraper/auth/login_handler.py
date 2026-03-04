"""
Interactive login flow for X (Twitter).

Handles the multi-step login process:
1. Check for saved encrypted credentials
2. If not found, prompt for credentials in terminal and save them encrypted
3. Navigate to login page
4. Enter username and click next
5. Enter password and submit
6. Wait for successful redirect
7. Delete saved credentials only after successful login

Uses encrypted credential caching so users aren't re-prompted on every
retry or session expiration. Credentials are deleted only after
successful login.
"""

import getpass

from playwright.async_api import BrowserContext, Page
from loguru import logger

from utils.config import settings
from utils.retry import retry
from browser.session_manager import save_session
from auth.credential_manager import (
    save_credentials,
    load_credentials,
    delete_credentials,
)


@retry(max_attempts=2, base_delay=3.0, exceptions=(Exception,))
async def perform_login(page: Page, context: BrowserContext) -> None:
    """
    Execute the full X login flow with credential caching.

    On first login, prompts for credentials and saves them encrypted.
    On retries or subsequent runs, reuses saved credentials.
    Credentials are deleted only after successful login.

    Args:
        page: The active Playwright page.
        context: The browser context (needed for session saving).

    Raises:
        Exception: If login fails after all retry attempts.
    """
    logger.info("Starting login flow")

    # Try to load saved credentials first
    saved = load_credentials()
    if saved:
        username, password = saved
        logger.info("Using saved credentials for user: {}", username)
    else:
        # Prompt for credentials in terminal
        print("\n" + "=" * 50)
        print("  X (Twitter) Login Required")
        print("=" * 50)
        username = input("  Enter username or email: ").strip()
        password = getpass.getpass("  Enter password: ")
        print("=" * 50 + "\n")

        if not username or not password:
            raise ValueError("Username and password are required")

        # Save credentials encrypted for retry resilience
        save_credentials(username, password)

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

    # Step 6: Save session and delete credentials (login succeeded)
    await save_session(context)
    delete_credentials()
    logger.info("Login flow completed, session saved, credentials cleared")
