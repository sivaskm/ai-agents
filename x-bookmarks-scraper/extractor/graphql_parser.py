"""
Parser for X (Twitter) GraphQL API bookmark responses.
Converts the complex nested JSON structure into our clean Bookmark Pydantic models.
"""
from typing import Dict, List, Optional, Tuple

from storage.bookmark_model import Bookmark
from utils.logger import logger
from extractor.tweet_extractor import _normalize_links


def parse_bookmarks_response(response_data: dict) -> Tuple[List[Bookmark], Optional[str]]:
    """
    Parse a GraphQL bookmarks response into Bookmark models and a pagination cursor.

    Args:
        response_data: The JSON payload from `/i/api/graphql/.../Bookmarks`.

    Returns:
        A tuple of (List of Bookmarks, Next Cursor string or None).
    """
    bookmarks: List[Bookmark] = []
    next_cursor: Optional[str] = None
    
    try:
        # Navigate the deeply nested GraphQL structure
        data = response_data.get("data", {})
        timeline_v2 = data.get("bookmark_timeline_v2", {})
        timeline = timeline_v2.get("timeline", {})
        instructions = timeline.get("instructions", [])
        
        if not instructions:
            logger.warning("GraphQL response missing 'instructions' array.")
            return [], None
            
        entries = []
        for inst in instructions:
            if inst.get("type") == "TimelineAddEntries":
                entries = inst.get("entries", [])
                break
                
        if not entries:
            logger.debug("No entries found in GraphQL response.")
            return [], None

        for entry in entries:
            entry_id = entry.get("entryId", "")
            content = entry.get("content", {})
            
            # Check for pagination cursor
            if "cursor-bottom" in entry_id.lower() or content.get("cursorType") == "Bottom":
                next_cursor = content.get("value")
                continue
                
            # Skip top cursors and other non-tweet entries
            if "tweet-" not in entry_id.lower():
                continue
                
            bookmark = _parse_tweet_entry(entry)
            if bookmark:
                bookmarks.append(bookmark)
                
        return bookmarks, next_cursor
        
    except Exception as e:
        logger.error(f"Failed to parse GraphQL response: {e}")
        return [], None


def _parse_tweet_entry(entry: dict) -> Optional[Bookmark]:
    """Parse a single TimelineTimelineItem entry into a Bookmark."""
    try:
        content = entry.get("content", {})
        item_content = content.get("itemContent", {})
        
        if item_content.get("itemType") != "TimelineTweet":
            return None
            
        tweet_results = item_content.get("tweet_results", {})
        result = tweet_results.get("result", {})
        
        # Handle wrapper type (often used for quotes or sensitive content)
        if result.get("__typename") == "TweetWithVisibilityResults":
            result = result.get("tweet", {})
            
        # Needs to be a Tweet
        if result.get("__typename") != "Tweet":
            return None
            
        core = result.get("core", {})
        legacy = result.get("legacy", {})
        
        # 1. Tweet ID
        tweet_id = legacy.get("id_str") or result.get("rest_id")
        if not tweet_id:
            return None
            
        # 2. Author
        user_legacy = core.get("user_results", {}).get("result", {}).get("core", {})
        if not user_legacy:
            # Fallback path if X changes the structure slightly
            user_legacy = core.get("user_results", {}).get("result", {}).get("legacy", {})
        author = user_legacy.get("screen_name", "unknown")
        
        # 3. URL
        tweet_url = f"https://x.com/{author}/status/{tweet_id}"
        
        # 4. Text
        text = legacy.get("full_text", "")
        
        # 5. Media (Images)
        images = []
        entities = legacy.get("entities", {})
        extended_entities = legacy.get("extended_entities", entities)
        
        for media in extended_entities.get("media", []):
            if media.get("type") == "photo":
                img_url = media.get("media_url_https")
                if img_url:
                    images.append(img_url)
                    
        # 6. Links (External URLs, Cards, Quotes)
        card = result.get("card", {})
        quoted = result.get("quoted_status_result", {})
        raw_links = _extract_all_links(legacy, card, quoted)
        links = _normalize_links(raw_links, text)
        
        # 7. Thread Detection
        # A thread is when the user replies to themselves.
        # However, the GraphQL bookmarks API generally only returns the exact bookmarked tweet,
        # not the entire thread unrolled. So if conversation_id != tweet_id, it is a reply IN a thread.
        # If we need the full thread, the GraphQL API handles that differently. For now, we capture what's returned.
        # But let's check if there's self-thread structure available.
        # Often, thread replies aren't nested in the Bookmark payload; only the specific bookmarked tweet is.
        # We will assume is_thread = False for the isolated object unless it's a known thread root.
        conversation_id = legacy.get("conversation_id_str")
        # For full thread parity with DOM mode, we might need a separate API call.
        # But usually bookmarks are individual tweets. If the user bookmarked a thread, 
        # the API provides the single tweet. We'll set is_thread=False for now and thread=[] 
        # to match single-tweet extraction, unless we see nested threads in the API response.
        
        return Bookmark(
            tweet_id=tweet_id,
            author=author,
            text=text,
            url=tweet_url,
            images=images,
            links=links,
            is_thread=False,
            thread=[]
        )
        
    except Exception as e:
        logger.warning(f"Error parsing individual tweet entry: {e}")
        return None


def _extract_all_links(legacy: dict, card: dict, quoted: dict) -> List[str]:
    """Extract all URLs from the tweet entities, card metadata, and quoted tweets."""
    links = []
    
    # Text URLs (already resolved to their expanded_url by X API!)
    urls = legacy.get("entities", {}).get("urls", [])
    for u in urls:
        expanded = u.get("expanded_url")
        if expanded:
            links.append(expanded)
            
    # Card URLs
    if card:
        card_legacy = card.get("legacy", {})
        for bv in card_legacy.get("binding_values", []):
            if bv.get("key") == "card_url":
                val = bv.get("value", {}).get("string_value")
                if val:
                    links.append(val)
                    
    # Quoted Tweets (internal X permalinks)
    if quoted:
        q_result = quoted.get("result", {})
        q_legacy = q_result.get("legacy", {})
        q_core = q_result.get("core", {})
        
        q_id = q_legacy.get("id_str")
        q_user = q_core.get("user_results", {}).get("result", {}).get("core", {})
        q_author = q_user.get("screen_name")
        
        if q_id and q_author:
            links.append(f"https://x.com/{q_author}/status/{q_id}")
            
    return links
