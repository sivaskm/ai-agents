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
    Distinguishes between [Quote Tweet] (internal X) and [Link Card] (external resource).
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
        # card.wrapper = external link cards (GitHub, YouTube, articles)
        card_wrappers = tweet.locator('[data-testid="card.wrapper"]')
        card_wrapper_count = await card_wrappers.count()
        for i in range(card_wrapper_count):
            card = card_wrappers.nth(i)
            card_text = await card.inner_text()
            if card_text:
                card_text = re.sub(r'\n+', '\n', card_text).strip()
                if card_text and card_text not in parts:
                    parts.append(f"[Link Card]\n{card_text}")
        
        # div[role="link"] without card.wrapper = quote tweets (internal X references)
        div_role_links = tweet.locator('div[role="link"]')
        div_count = await div_role_links.count()
        for i in range(div_count):
            div_link = div_role_links.nth(i)
            # Skip if this is inside a card.wrapper (already handled above)
            is_inside_card = await div_link.evaluate(
                'el => !!el.closest(\'[data-testid="card.wrapper"]\')'
            )
            if is_inside_card:
                continue
            div_text = await div_link.inner_text()
            if div_text:
                div_text = re.sub(r'\n+', '\n', div_text).strip()
                if div_text and div_text not in parts:
                    parts.append(f"[Quote Tweet]\n{div_text}")
                    
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
    
    Strategy:
    1. Regex over inline text for explicit URLs.
    2. Scan a[href] and [role="link"][href] for t.co and external links.
    3. Extract Quote Tweet permalinks from div[role="link"] (internal X refs).
    4. Extract card.wrapper nested a[href] links.
    
    Filters out navigation, media CDN, and duplicate URLs.
    """
    links: List[str] = []
    
    # 1. Regex over inline cleartext
    if tweet_text:
        urls_in_text = re.findall(r'https?://[^\s\n\r]+', tweet_text)
        for url in urls_in_text:
            links.append(url)

    # 2. Extract DOM-level links from a[href] elements
    try:
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
    
    # 3. Extract Quote Tweet permalinks from div[role="link"] (no href on div itself)
    try:
        div_role_links = await tweet.locator('div[role="link"]').all()
        for div_link in div_role_links:
            # Skip if inside card.wrapper (handled by step 2 above)
            is_inside_card = await div_link.evaluate(
                'el => !!el.closest(\'[data-testid="card.wrapper"]\')'
            )
            if is_inside_card:
                continue
            
            # Look for nested a[href*="/status/"] — this is the quoted tweet permalink
            nested_permalinks = await div_link.locator('a[href*="/status/"]').all()
            for a in nested_permalinks:
                href = await a.get_attribute("href")
                if href and re.match(r'^/[^/]+/status/\d+', href):
                    full_url = f"https://x.com{href}"
                    if full_url not in links:
                        links.append(full_url)
                    break  # Only need the first permalink per quote tweet
    except Exception as exc:
        logger.debug("Minor error extracting quote tweet links: {}", exc)

    # 4. Explicitly scan card.wrapper for nested a[href] (catches t.co links in cards)
    try:
        card_wrappers = await tweet.locator('[data-testid="card.wrapper"]').all()
        for card in card_wrappers:
            card_anchors = await card.locator('a[href]').all()
            for a in card_anchors:
                href = await a.get_attribute("href")
                if href and not href.startswith("/"):
                    if "x.com" not in href and "twitter.com" not in href and "pbs.twimg.com" not in href:
                        links.append(href)
    except Exception as exc:
        logger.debug("Minor error extracting card wrapper links: {}", exc)

    # Deduplicate before returning
    return list(set(links))


async def _resolve_tco_url(page: Page, tco_url: str) -> str:
    """
    Resolve a t.co shortened URL to its final destination.
    Opens a new tab in the same browser context, navigates to the t.co URL
    (which triggers a 301/302 redirect), reads the final URL, then closes the tab.
    
    Args:
        page: The active Playwright page (used to access the browser context).
        tco_url: A t.co shortened URL.
    
    Returns:
        The resolved destination URL, or the original t.co URL on failure.
    """
    resolve_page = None
    try:
        context = page.context
        resolve_page = await context.new_page()
        # Navigate to t.co — the browser will follow the redirect automatically
        response = await resolve_page.goto(tco_url, wait_until="domcontentloaded", timeout=10000)
        resolved = resolve_page.url
        if resolved and resolved != tco_url and "t.co" not in resolved:
            logger.debug("Resolved {} → {}", tco_url, resolved)
            return resolved
    except Exception as exc:
        logger.debug("Failed to resolve t.co URL {}: {}", tco_url, exc)
    finally:
        if resolve_page:
            try:
                await resolve_page.close()
            except Exception:
                pass
    return tco_url


async def _resolve_all_tco_links(page: Page, links: List[str]) -> List[str]:
    """
    Resolve all t.co shortened URLs in a links list to their final destinations.
    Non-t.co links are passed through unchanged.
    
    Args:
        page: The active Playwright page.
        links: List of URLs (may contain t.co shortened URLs).
    
    Returns:
        List of URLs with t.co links replaced by their final destinations.
    """
    resolved_links: List[str] = []
    for link in links:
        if "t.co/" in link:
            resolved = await _resolve_tco_url(page, link)
            resolved_links.append(resolved)
        else:
            resolved_links.append(link)
    
    # Deduplicate after resolution (different t.co links may point to same destination)
    return list(dict.fromkeys(resolved_links))


def _normalize_links(links: List[str], tweet_text: str = "") -> List[str]:
    """
    Normalize and deduplicate a list of extracted links.
    
    Rules applied (in order):
    1. Remove any remaining t.co links (already resolved to destinations)
    2. Remove truncated URLs ending in '…' if a full version exists
    3. Remove card metadata canonical URLs that don't appear in tweet text
       (e.g., card resolves tensortonic.com but tweet only mentions takeubackward.org)
    4. Final deduplication on cleaned URLs
    
    Args:
        links: Raw extracted + resolved links list.
        tweet_text: The tweet text for cross-referencing which URLs the author mentioned.
    
    Returns:
        Cleaned, deduplicated list of links.
    """
    if not links:
        return []
    
    # Step 1: Remove any remaining t.co links
    cleaned = [l for l in links if "t.co/" not in l]
    
    # Step 2: Remove truncated '…' URLs when a more complete version exists
    # A truncated URL is one that ends with '…' (Unicode ellipsis)
    truncated = [l for l in cleaned if l.endswith("…")]
    non_truncated = [l for l in cleaned if not l.endswith("…")]
    
    for trunc_url in truncated:
        # Strip the ellipsis to get the base prefix
        base = trunc_url.rstrip("…")
        # Check if any non-truncated URL starts with the same base
        has_full_version = any(nt.startswith(base) for nt in non_truncated)
        if not has_full_version:
            # No full version exists — keep the truncated version (strip the …)
            non_truncated.append(base)
    
    cleaned = non_truncated
    
    # Step 3: Remove card metadata canonical URLs that differ from tweet text URLs.
    # If a link was NOT mentioned anywhere in the tweet text AND a different link
    # from the same tweet WAS mentioned, the unmentioned one is likely a card redirect.
    # Only apply if we have text-referenced links to compare against.
    if tweet_text and len(cleaned) > 1:
        text_lower = tweet_text.lower()
        text_referenced = []
        card_only = []
        
        for link in cleaned:
            # Check if any significant part of the link appears in the tweet text
            # Extract domain from URL for matching
            url_for_check = link.lower().replace("https://", "").replace("http://", "").replace("www.", "")
            domain = url_for_check.split("/")[0] if "/" in url_for_check else url_for_check
            
            # An x.com link (quote tweet permalink) is always kept
            if "x.com/" in link:
                text_referenced.append(link)
            elif domain in text_lower or link.lower() in text_lower:
                text_referenced.append(link)
            else:
                card_only.append(link)
        
        # Only remove card-only links if we have at least one text-referenced link
        if text_referenced:
            cleaned = text_referenced
        # else keep all links (no text references found, don't throw anything away)
    
    # Step 4: Final deduplication preserving order
    return list(dict.fromkeys(cleaned))


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

    is_thread = len(thread_texts) > 0

    if is_thread:
        logger.info(
            "🧵 Thread detected! {} reply tweets by @{}", len(thread_texts), author
        )

    # --- Resolve t.co shortened URLs to their actual destinations ---
    if all_links:
        all_links = await _resolve_all_tco_links(page, all_links)

    # --- Normalize links: remove truncated duplicates, card metadata noise, t.co remnants ---
    # Combine main text + thread texts for cross-referencing link mentions
    full_text = main_text
    if thread_texts:
        full_text += "\n" + "\n".join(thread_texts)
    all_links = _normalize_links(all_links, full_text)

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


async def remove_bookmark_from_ui(page: Page) -> bool:
    """
    Remove the current tweet from bookmarks by clicking the unbookmark button.

    Twitter uses data-testid="removeBookmark" for the button that removes
    an existing bookmark (as opposed to data-testid="bookmark" which ADDS one).

    Steps:
        1. Scroll to top so the main tweet's action bar is visible
        2. Scope the search to the first tweet element to avoid clicking
           removeBookmark on a reply tweet
        3. Scroll the button into view and click it
        4. Handle any confirmation dialog Twitter may show
        5. Verify the button changed to "bookmark" (add state)

    Returns:
        True if removal was successful, False otherwise.
    """
    try:
        # Scroll to top — after thread extraction the page may be scrolled down
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(500)

        # Scope to the first tweet element (the main/bookmarked tweet)
        first_tweet = page.locator('[data-testid="tweet"]').first
        if await first_tweet.count() == 0:
            logger.warning("No tweet element found on page")
            return False

        # Find the removeBookmark button within the first tweet
        remove_btn = first_tweet.locator('[data-testid="removeBookmark"]')

        if await remove_btn.count() == 0:
            # Fallback: try page-level search (some layouts nest differently)
            remove_btn = page.locator('[data-testid="removeBookmark"]').first
            if await remove_btn.count() == 0:
                logger.warning("Could not find removeBookmark button — tweet may not be bookmarked")
                return False

        # Scroll the button into view before clicking
        await remove_btn.first.scroll_into_view_if_needed(timeout=3000)
        await page.wait_for_timeout(300)

        # Click the removeBookmark button
        await remove_btn.first.click(timeout=5000)
        await page.wait_for_timeout(1500)

        # Handle any confirmation dialog (Twitter sometimes shows "Remove from Bookmarks?")
        try:
            confirm_btn = page.locator('[data-testid="confirmationSheetConfirm"]')
            if await confirm_btn.count() > 0:
                await confirm_btn.click(timeout=3000)
                await page.wait_for_timeout(1000)
                logger.debug("Dismissed confirmation dialog")
        except Exception:
            pass  # No confirmation dialog — that's fine

        # Verify: after clicking, the button should change to data-testid="bookmark"
        add_btn = first_tweet.locator('[data-testid="bookmark"]')
        if await add_btn.count() > 0:
            logger.info("🗑 Bookmark removed successfully (verified)")
            return True
        else:
            # Button was clicked but state didn't visibly change — may still have worked
            logger.info("🗑 Bookmark remove clicked (unverified)")
            return True

    except Exception as exc:
        logger.warning("Failed to remove bookmark: {}", exc)
        return False


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
