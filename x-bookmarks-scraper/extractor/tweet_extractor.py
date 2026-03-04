"""
Tweet data extractor — unified parser for text, author, URL, and images.

Extracts structured bookmark data directly from the DOM without clicking
into individual tweets. Operates on [data-testid="tweet"] elements and
uses stable data-testid selectors wherever possible.

Design decisions:
    - Merged tweet_parser and image_parser into a single module because both
      operate on the same tweet DOM node, reducing redundant element lookups.
    - Uses a seen_ids set to skip already-processed tweets during scroll,
      dramatically improving extraction speed.
    - Extracts tweet_id from the permalink URL for stable deduplication.
"""

import re
from typing import List, Set

from playwright.async_api import Locator, Page
from loguru import logger

from storage.bookmark_model import Bookmark


async def extract_all_bookmarks(
    page: Page,
    seen_ids: Set[str] | None = None,
    max_tweets: int = 0,
) -> List[Bookmark]:
    """
    Extract bookmark data from all visible tweet elements on the page.

    Args:
        page: The active Playwright page (should be on bookmarks).
        seen_ids: Optional set of already-processed tweet IDs to skip.
                  Will be updated in-place with newly extracted IDs.
        max_tweets: Maximum number of bookmarks to extract (0 = all).

    Returns:
        List of newly extracted Bookmark objects (excludes seen_ids).
    """
    if seen_ids is None:
        seen_ids = set()

    bookmarks: List[Bookmark] = []
    tweets = page.locator('[data-testid="tweet"]')
    count = await tweets.count()

    logger.info("Extracting data from {} tweet elements", count)

    for i in range(count):
        tweet = tweets.nth(i)

        try:
            bookmark = await _extract_single_tweet(tweet)

            if bookmark is None:
                continue

            # Anti-duplicate cache: skip already-seen tweets
            if bookmark.tweet_id in seen_ids:
                continue

            seen_ids.add(bookmark.tweet_id)
            bookmarks.append(bookmark)

            # Enforce max_tweets limit
            if max_tweets > 0 and len(bookmarks) >= max_tweets:
                logger.info("Reached max tweet extraction limit ({})", max_tweets)
                break

        except Exception as exc:
            logger.warning("Failed to extract tweet #{}: {}", i, exc)
            continue

    logger.info(
        "Extracted {} new bookmarks ({} skipped as duplicates)",
        len(bookmarks),
        count - len(bookmarks),
    )
    return bookmarks


async def _extract_single_tweet(tweet: Locator) -> Bookmark | None:
    """
    Extract data from a single tweet DOM element.

    The X tweet DOM structure (simplified):
        [data-testid="tweet"]
            └─ [data-testid="User-Name"]  → author info
            └─ [data-testid="tweetText"]  → tweet content
            └─ a[href*="/status/"]        → permalink with tweet ID
            └─ [data-testid="tweetPhoto"] img → media images

    Args:
        tweet: A Playwright locator pointing to a single [data-testid="tweet"] element.

    Returns:
        A Bookmark object, or None if the tweet couldn't be parsed.
    """
    # --- Extract tweet URL and ID ---
    tweet_url = ""
    tweet_id = ""

    # Find the permalink link containing "/status/"
    permalink_links = tweet.locator('a[href*="/status/"]')
    link_count = await permalink_links.count()

    for j in range(link_count):
        href = await permalink_links.nth(j).get_attribute("href")
        if href and "/status/" in href:
            # Match only the clean status URL (no /photo, /analytics, etc.)
            if re.match(r"^/[^/]+/status/\d+$", href):
                tweet_url = f"https://x.com{href}"
                # Extract tweet ID from URL: /user/status/1234567890 → 1234567890
                match = re.search(r"/status/(\d+)", href)
                if match:
                    tweet_id = match.group(1)
                break

    if not tweet_id:
        # Can't identify tweet without an ID — skip
        return None

    # --- Extract author ---
    author = "unknown"
    try:
        # The User-Name element contains both display name and @handle
        user_name_element = tweet.locator('[data-testid="User-Name"]')
        if await user_name_element.count() > 0:
            # Look for the @handle link within the user name area
            handle_links = user_name_element.locator('a[href^="/"]')
            for j in range(await handle_links.count()):
                href = await handle_links.nth(j).get_attribute("href")
                if href and href.startswith("/") and "/status/" not in href:
                    author = href.strip("/")
                    break
    except Exception:
        pass

    # --- Extract tweet text ---
    # Use text_content() to get the full text from the DOM, including content
    # that may be visually truncated with "Show more" in the timeline view.
    # inner_text() only returns visible text, which can be truncated.
    text = ""
    try:
        text_elements = tweet.locator('[data-testid="tweetText"]')
        text_count = await text_elements.count()
        if text_count > 0:
            # Collect text from all tweetText elements (handles threads/quote tweets)
            text_parts = []
            for idx in range(text_count):
                part = await text_elements.nth(idx).text_content()
                if part:
                    text_parts.append(part.strip())
            text = "\n\n".join(text_parts)
    except Exception:
        pass

    # --- Extract images ---
    images = await _extract_images(tweet)

    return Bookmark(
        tweet_id=tweet_id,
        author=author,
        text=text,
        url=tweet_url,
        images=images,
    )


async def _extract_images(tweet: Locator) -> List[str]:
    """
    Extract image URLs from a tweet's media section.

    Looks for img elements within [data-testid="tweetPhoto"] containers.
    Filters out profile pictures and emoji by checking URL patterns.

    Args:
        tweet: A Playwright locator for a single tweet element.

    Returns:
        List of image URLs found in the tweet.
    """
    images: List[str] = []

    try:
        photo_containers = tweet.locator('[data-testid="tweetPhoto"] img')
        img_count = await photo_containers.count()

        for i in range(img_count):
            src = await photo_containers.nth(i).get_attribute("src")
            if src and "pbs.twimg.com/media" in src:
                # Clean the URL — remove any format parameters and get highest quality
                clean_url = re.sub(r"\?.*$", "", src)
                if clean_url not in images:
                    images.append(src)  # Keep original URL with format params
    except Exception:
        pass

    return images
