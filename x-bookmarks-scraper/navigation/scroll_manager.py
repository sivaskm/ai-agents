"""
Infinite scroll manager for bookmark loading.

Implements a robust scroll strategy that:
1. Scrolls the last visible tweet into view (more reliable than page scroll)
2. Waits for new content to load
3. Counts tweets and stops when no new ones appear
4. Adds human-like random delays to avoid detection
5. Supports a max-tweet cap via configuration

This approach is preferred over raw page.evaluate("window.scrollTo()") because
scrolling a specific element triggers X's infinite scroll more reliably.
"""

import asyncio
import random

from playwright.async_api import Page
from loguru import logger

from utils.config import settings


async def scroll_to_load_all(
    page: Page,
    max_tweets: int = 0,
    scroll_delay: float | None = None,
    max_retries: int | None = None,
) -> int:
    """
    Scroll the bookmarks page to load all available tweets.

    Uses the "scroll last tweet into view" strategy for reliable loading.
    Stops when no new tweets appear after max_retries consecutive scrolls,
    or when max_tweets is reached.

    Args:
        page: The active Playwright page (should be on bookmarks).
        max_tweets: Maximum tweets to collect (0 = unlimited). Overrides settings.
        scroll_delay: Base delay between scrolls in seconds. Overrides settings.
        max_retries: Max consecutive no-new-tweet scrolls. Overrides settings.

    Returns:
        Total number of tweets loaded on the page.
    """
    max_tweets = max_tweets or settings.max_tweets
    delay = scroll_delay or settings.scroll_delay
    retries = max_retries or settings.max_scroll_retries

    tweet_selector = '[data-testid="tweet"]'
    previous_count = 0
    no_new_count = 0
    scroll_round = 0

    logger.info(
        "Starting infinite scroll (max_tweets={}, scroll_delay={:.1f}s, max_retries={})",
        max_tweets or "unlimited",
        delay,
        retries,
    )

    while True:
        scroll_round += 1

        # Scroll the last visible tweet into view
        tweets = page.locator(tweet_selector)
        current_count = await tweets.count()

        if current_count > 0:
            last_tweet = tweets.last
            try:
                await last_tweet.scroll_into_view_if_needed(timeout=5000)
            except Exception as exc:
                logger.debug("Scroll into view failed ({}), using page scroll fallback", exc)
                await page.evaluate("window.scrollBy(0, window.innerHeight)")

        # Human-like random delay to avoid detection
        jittered_delay = delay + random.uniform(0.5, 1.5)
        await asyncio.sleep(jittered_delay)

        # Wait for potential new content to render
        try:
            await page.wait_for_timeout(1000)
        except Exception:
            pass

        # Count tweets after scroll
        current_count = await tweets.count()

        # Log progress
        if current_count > previous_count:
            new_in_round = current_count - previous_count
            logger.info(
                "Scroll #{}: {} tweets loaded (+{} new)",
                scroll_round,
                current_count,
                new_in_round,
            )
            no_new_count = 0
        else:
            no_new_count += 1
            logger.debug(
                "Scroll #{}: No new tweets ({}/{} retries)",
                scroll_round,
                no_new_count,
                retries,
            )

        # Check stop conditions
        if max_tweets > 0 and current_count >= max_tweets:
            logger.info(
                "Reached max tweet limit ({}/{}). Stopping scroll.",
                current_count,
                max_tweets,
            )
            break

        if no_new_count >= retries:
            logger.info(
                "No new tweets after {} consecutive scrolls. All bookmarks loaded.",
                retries,
            )
            break

        previous_count = current_count

    final_count = await page.locator(tweet_selector).count()
    logger.info("Scroll complete. Total tweets on page: {}", final_count)
    return final_count
