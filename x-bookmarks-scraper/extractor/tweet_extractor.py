"""
Tweet data extractor — click-into-tweet strategy with thread unrolling.

Extracts full content from tweet detail pages. Detects threads
(consecutive tweets by the same author) and unrolls them automatically.

Thread detection strategy:
    On the tweet detail page, X shows the main tweet followed by replies.
    If consecutive replies are from the same author as the main tweet,
    it's a thread. We extract all same-author tweets until we hit a
    different author or run out of tweets.

Design decisions:
    - Navigates to each tweet's detail page for full untruncated content.
    - Detects threads by checking consecutive same-author tweets.
    - Thread tweets are stored as a list in the 'thread' field.
    - Images are collected from ALL tweets in a thread.
    - Uses tweet_id from permalink URL as primary key for deduplication.
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


async def _extract_author_from_tweet(tweet: Locator) -> str:
    """
    Extract the @handle from a single tweet element.

    Args:
        tweet: Locator for a [data-testid="tweet"] element.

    Returns:
        The author handle string (without @), or "unknown".
    """
    try:
        user_name_element = tweet.locator('[data-testid="User-Name"]')
        if await user_name_element.count() > 0:
            handle_links = user_name_element.locator('a[href^="/"]')
            for j in range(await handle_links.count()):
                href = await handle_links.nth(j).get_attribute("href")
                if href and href.startswith("/") and "/status/" not in href:
                    return href.strip("/")
    except Exception:
        pass
    return "unknown"


async def _extract_text_from_tweet(tweet: Locator) -> str:
    """
    Extract full text content from a single tweet element.
    Uses text_content() for DOM-level text (not truncated).
    Also checks for attached link cards or quote tweets.
    """
    parts = []
    try:
        # 1. Main tweet text
        text_elements = tweet.locator('[data-testid="tweetText"]')
        if await text_elements.count() > 0:
            text = await text_elements.first.text_content() or ""
            text = text.strip()
            if text:
                parts.append(text)
                
        # 2. Attached Cards, Articles, or Quote Tweets
        # These are usually contained in div[role="link"] or card wrappers
        cards = tweet.locator('div[role="link"], [data-testid="card.wrapper"]')
        card_count = await cards.count()
        for i in range(card_count):
            card = cards.nth(i)
            # inner_text() gets the visible text of the card (title, description, domain)
            card_text = await card.inner_text()
            if card_text:
                # Clean up multiple newlines from card extraction
                card_text = re.sub(r'\n+', '\n', card_text).strip()
                if card_text and card_text not in parts:
                    parts.append(f"[Card/Quote]\n{card_text}")
                    
        return "\n\n".join(parts).strip()
    except Exception:
        pass
    return ""


async def _extract_images_from_tweet(tweet: Locator) -> List[str]:
    """
    Extract image URLs from a single tweet element.

    Args:
        tweet: Locator for a [data-testid="tweet"] element.

    Returns:
        List of image URLs.
    """
    images: List[str] = []
    try:
        photo_containers = tweet.locator('[data-testid="tweetPhoto"] img')
        img_count = await photo_containers.count()
        for i in range(img_count):
            src = await photo_containers.nth(i).get_attribute("src")
            if src and "pbs.twimg.com/media" in src:
                if src not in images:
                    images.append(src)
    except Exception:
        pass
    return images


async def _extract_links_from_tweet(tweet: Locator, tweet_text: str = "") -> List[str]:
    """
    Extract external destination links from a tweet.
    
    1. Scans ARIA [role="link"] elements for associated hrefs (used in OpenGraph/Cards).
    2. Scans standard a[href] elements.
    3. Scans the raw text via regex for inline URLs.
    Filters out internal X/Twitter navigation and media CDN URLs.
    """
    links: List[str] = []
    
    # 1. Regex over inline cleartext
    if tweet_text:
        urls_in_text = re.findall(r'https?://[^\s\n\r]+', tweet_text)
        for url in urls_in_text:
            links.append(url)

    # 2. Extract DOM-level links using precise role=link to avoid noise
    try:
        # X highly leverages role="link" for active interactive cards
        anchors = await tweet.locator('a[href], [role="link"][href]').all()
        for a in anchors:
            href = await a.get_attribute("href")
            if not href:
                continue
                
            # Discard relative internal paths
            if href.startswith("/"):
                continue
                
            # Discard absolute internal paths
            if "x.com" in href or "twitter.com" in href:
                continue

            # Discard media links
            if "pbs.twimg.com" in href:
                continue

            links.append(href)
    except Exception as exc:
        logger.debug("Minor error extracting DOM links: {}", exc)

    # Deduplicate before returning
    return list(set(links))


async def extract_from_detail_page(page: Page) -> Optional[Bookmark]:
    """
    Extract full tweet data from a tweet's detail page, with thread unrolling.

    On the detail page, X shows the main tweet first, followed by replies.
    If the replies are from the same author, it's a thread — we unroll it
    by extracting all consecutive same-author tweets.

    Thread detection algorithm:
        1. Extract author of the main tweet (first [data-testid="tweet"])
        2. Look at subsequent tweet elements on the page
        3. If the next tweet is by the same author → it's part of the thread
        4. If the next tweet is by a different author → stop (conversation, not thread)
        5. Collect all thread texts into a list

    Args:
        page: The Playwright page currently showing a tweet detail view.

    Returns:
        A Bookmark object (with thread if detected), or None on failure.
    """
    try:
        # Wait for tweets to load on the detail page
        first_tweet = page.locator('[data-testid="tweet"]').first
        await first_tweet.wait_for(state="visible", timeout=10000)
        
        # Wait for replies to load from the API and render in DOM
        await page.wait_for_timeout(2500)
        
        # Scroll down slightly to trigger lazy loading of replies
        await page.evaluate("window.scrollBy(0, 400)")
        await page.wait_for_timeout(1000)
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

    # --- Get all tweet elements on the detail page ---
    all_tweets = page.locator('[data-testid="tweet"]')
    tweet_count = await all_tweets.count()

    if tweet_count == 0:
        return None

    # --- Extract main tweet (first one) ---
    main_tweet = all_tweets.first
    author = await _extract_author_from_tweet(main_tweet)
    main_text = await _extract_text_from_tweet(main_tweet)
    all_images = await _extract_images_from_tweet(main_tweet)
    all_links = await _extract_links_from_tweet(main_tweet, main_text)

    # --- Thread detection with pagination: check consecutive same-author tweets ---
    # Fix: DO NOT insert the root main_text into the thread array. The thread array should only contain REPLIES.
    thread_texts: List[str] = []
    seen_texts: Set[str] = {main_text} if main_text else set()
    is_thread = False

    max_scrolls = 15  # Prevent infinite loops on very long threads
    no_new_tweets_rounds = 0

    for scroll_round in range(max_scrolls):
        all_tweets = page.locator('[data-testid="tweet"]')
        current_count = await all_tweets.count()
        found_new_in_round = False
        author_changed = False

        for i in range(current_count):
            reply_tweet = all_tweets.nth(i)
            try:
                reply_author = await _extract_author_from_tweet(reply_tweet)
                
                # Skip ads or elements where author extraction failed
                if reply_author == "unknown":
                    continue
                    
                if reply_author != author:
                    logger.info("Author changed to {}. End of thread replies.", reply_author)
                    author_changed = True
                    break

                reply_text = await _extract_text_from_tweet(reply_tweet)
                if reply_text and reply_text not in seen_texts:
                    thread_texts.append(reply_text)
                    seen_texts.add(reply_text)
                    found_new_in_round = True
                    
                    # Collect images from thread tweets too
                    reply_images = await _extract_images_from_tweet(reply_tweet)
                    for img in reply_images:
                        if img not in all_images:
                            all_images.append(img)
                            
                    # Collect links from thread tweets too
                    reply_links = await _extract_links_from_tweet(reply_tweet, reply_text)
                    for link in reply_links:
                        if link not in all_links:
                            all_links.append(link)
                            
            except Exception:
                continue

        if author_changed:
            break
            
        if not found_new_in_round:
            no_new_tweets_rounds += 1
            if no_new_tweets_rounds >= 2:
                # No new thread tweets found after 2 scrolls -> end of thread
                break
        else:
            no_new_tweets_rounds = 0
            
        # Scroll down to load the next chunk of the thread
        await page.evaluate("window.scrollBy(0, 800)")
        await page.wait_for_timeout(1500)

    is_thread = len(thread_texts) > 1

    if is_thread:
        logger.info(
            "🧵 Thread detected! {} tweets by @{}", len(thread_texts), author
        )

    return Bookmark(
        tweet_id=tweet_id,
        author=author,
        text=main_text,
        url=current_url,
        images=all_images,
        links=all_links,
        is_thread=is_thread,
        thread=thread_texts if is_thread else [],
    )


async def click_tweet_and_extract(
    page: Page,
    tweet_info: dict,
    bookmarks_url: str,
) -> Optional[Bookmark]:
    """
    Navigate to a tweet's detail page, extract full data with thread support.

    Args:
        page: The active Playwright page on bookmarks.
        tweet_info: Dict with 'tweet_id', 'url', and 'index'.
        bookmarks_url: URL of the bookmarks page to navigate back to.

    Returns:
        A Bookmark object (with thread if applicable), or None on failure.
    """
    tweet_id = tweet_info["tweet_id"]
    tweet_url = tweet_info["url"]

    try:
        logger.debug("Opening tweet {} for full extraction", tweet_id)

        # Navigate directly to the tweet URL
        await page.goto(tweet_url, wait_until="domcontentloaded", timeout=20000)

        # Wait for the detail page to load
        await page.wait_for_timeout(1500)

        # Extract full tweet data (with thread detection)
        bookmark = await extract_from_detail_page(page)

        if bookmark:
            if bookmark.is_thread:
                logger.debug(
                    "Extracted thread {}: {} parts, {} images",
                    tweet_id,
                    len(bookmark.thread),
                    len(bookmark.images),
                )
            else:
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
