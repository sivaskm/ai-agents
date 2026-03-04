"""
Tweet data extractor — click-into-tweet strategy for full content.

Instead of extracting from the timeline preview (which truncates text),
this module clicks into each tweet's detail page to get the complete
content including full text, all images, and proper metadata.

Design decisions:
    - Clicks each tweet to open its detail view for full content extraction.
    - Uses tweet_id from permalink URL as primary key for deduplication.
    - Extracts full text using text_content() on the detail page.
    - Returns to bookmarks page after each extraction.
    - Works within X's DOM virtualization (tweets removed from DOM during scroll).
"""

import re
from typing import List, Optional, Set

from playwright.async_api import Locator, Page
from loguru import logger

from storage.bookmark_model import Bookmark


async def collect_visible_tweet_links(page: Page, seen_ids: Set[str]) -> List[dict]:
    """
    Collect tweet permalink URLs and IDs from currently visible tweets.

    Only returns tweets not already in seen_ids. Does NOT click into tweets.
    This is used by the scroll+extract loop to find new tweets to process.

    Args:
        page: The active Playwright page on bookmarks.
        seen_ids: Set of already-processed tweet IDs to skip.

    Returns:
        List of dicts with 'tweet_id', 'url', and 'index' for each new tweet.
    """
    new_tweets = []
    tweets = page.locator('[data-testid="tweet"]')
    count = await tweets.count()

    for i in range(count):
        tweet = tweets.nth(i)
        try:
            # Find the permalink link to get tweet ID
            permalink_links = tweet.locator('a[href*="/status/"]')
            link_count = await permalink_links.count()

            for j in range(link_count):
                href = await permalink_links.nth(j).get_attribute("href")
                if href and re.match(r"^/[^/]+/status/\d+$", href):
                    match = re.search(r"/status/(\d+)", href)
                    if match:
                        tweet_id = match.group(1)
                        if tweet_id not in seen_ids:
                            new_tweets.append({
                                "tweet_id": tweet_id,
                                "url": f"https://x.com{href}",
                                "index": i,
                            })
                    break
        except Exception:
            continue

    return new_tweets


async def extract_from_detail_page(page: Page) -> Optional[Bookmark]:
    """
    Extract full tweet data from a tweet's detail page.

    Must be called when the page is already on a tweet's detail view
    (e.g., https://x.com/user/status/12345).

    The detail page shows the full untruncated tweet text, all images,
    and the complete author information.

    Args:
        page: The Playwright page currently showing a tweet detail view.

    Returns:
        A Bookmark object, or None if extraction failed.
    """
    try:
        # Wait for the tweet detail to load
        tweet_detail = page.locator('[data-testid="tweet"]').first
        await tweet_detail.wait_for(state="visible", timeout=10000)
    except Exception as exc:
        logger.warning("Tweet detail page failed to load: {}", exc)
        return None

    # --- Extract tweet ID and URL from the current page URL ---
    current_url = page.url
    match = re.search(r"/status/(\d+)", current_url)
    if not match:
        logger.warning("Could not extract tweet ID from URL: {}", current_url)
        return None

    tweet_id = match.group(1)

    # --- Extract author ---
    author = "unknown"
    try:
        # On the detail page, the first tweet is the main tweet
        user_name_element = tweet_detail.locator('[data-testid="User-Name"]')
        if await user_name_element.count() > 0:
            handle_links = user_name_element.locator('a[href^="/"]')
            for j in range(await handle_links.count()):
                href = await handle_links.nth(j).get_attribute("href")
                if href and href.startswith("/") and "/status/" not in href:
                    author = href.strip("/")
                    break
    except Exception:
        pass

    # --- Extract FULL tweet text ---
    # On the detail page, the text is not truncated
    text = ""
    try:
        text_elements = tweet_detail.locator('[data-testid="tweetText"]')
        text_count = await text_elements.count()
        if text_count > 0:
            # The first tweetText on the detail page is the main tweet's full text
            text = await text_elements.first.text_content() or ""
            text = text.strip()
    except Exception:
        pass

    # --- Extract images ---
    images = []
    try:
        photo_containers = tweet_detail.locator('[data-testid="tweetPhoto"] img')
        img_count = await photo_containers.count()

        for i in range(img_count):
            src = await photo_containers.nth(i).get_attribute("src")
            if src and "pbs.twimg.com/media" in src:
                if src not in images:
                    images.append(src)
    except Exception:
        pass

    return Bookmark(
        tweet_id=tweet_id,
        author=author,
        text=text,
        url=current_url,
        images=images,
    )


async def click_tweet_and_extract(
    page: Page,
    tweet_info: dict,
    bookmarks_url: str,
) -> Optional[Bookmark]:
    """
    Click into a tweet from the bookmarks page, extract full data, and return.

    Args:
        page: The active Playwright page on bookmarks.
        tweet_info: Dict with 'tweet_id', 'url', and 'index'.
        bookmarks_url: URL of the bookmarks page to navigate back to.

    Returns:
        A Bookmark object, or None if extraction failed.
    """
    tweet_id = tweet_info["tweet_id"]
    tweet_url = tweet_info["url"]

    try:
        logger.debug("Opening tweet {} for full extraction", tweet_id)

        # Navigate directly to the tweet URL (more reliable than clicking)
        await page.goto(tweet_url, wait_until="domcontentloaded", timeout=20000)

        # Wait for the detail page to load
        await page.wait_for_timeout(1500)

        # Extract full tweet data from the detail page
        bookmark = await extract_from_detail_page(page)

        if bookmark:
            logger.debug(
                "Extracted tweet {}: {} chars, {} images",
                tweet_id,
                len(bookmark.text),
                len(bookmark.images),
            )

        return bookmark

    except Exception as exc:
        logger.warning("Failed to extract tweet {}: {}", tweet_id, exc)
        return None
