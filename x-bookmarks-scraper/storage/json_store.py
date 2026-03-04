"""
JSON file storage for bookmarks with incremental saving.

Provides both batch save and incremental append functionality.
Each bookmark is saved immediately after extraction to prevent
data loss during long scraping sessions.
"""

import json
from pathlib import Path
from typing import List, Set

from loguru import logger

from storage.bookmark_model import Bookmark


def save_bookmarks(bookmarks: List[Bookmark], output_path: Path) -> None:
    """
    Save bookmarks to a JSON file, merging with any existing data.

    New bookmarks are merged with previously saved ones, deduplicated
    by tweet_id. This supports incremental scraping across sessions.

    Args:
        bookmarks: List of Bookmark objects to save.
        output_path: Path to the output JSON file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    existing = load_bookmarks(output_path)
    existing_ids = {b.tweet_id for b in existing}

    new_count = 0
    for bookmark in bookmarks:
        if bookmark.tweet_id not in existing_ids:
            existing.append(bookmark)
            existing_ids.add(bookmark.tweet_id)
            new_count += 1

    _write_bookmarks(existing, output_path)

    logger.info(
        "Saved {} bookmarks ({} new, {} existing) to {}",
        len(existing),
        new_count,
        len(existing) - new_count,
        output_path,
    )


def append_bookmark(bookmark: Bookmark, output_path: Path) -> bool:
    """
    Incrementally append a single bookmark to the JSON file.

    Loads existing data, checks for duplicates, appends if new,
    and writes back immediately. This ensures no data is lost
    if the scraper crashes mid-run.

    Args:
        bookmark: The Bookmark to append.
        output_path: Path to the output JSON file.

    Returns:
        True if the bookmark was new and appended, False if duplicate.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    existing = load_bookmarks(output_path)
    existing_ids = {b.tweet_id for b in existing}

    if bookmark.tweet_id in existing_ids:
        logger.debug("Bookmark {} already exists, skipping", bookmark.tweet_id)
        return False

    existing.append(bookmark)
    _write_bookmarks(existing, output_path)

    logger.info(
        "💾 Saved bookmark #{}: @{} — {}",
        len(existing),
        bookmark.author,
        bookmark.text[:60] + "..." if len(bookmark.text) > 60 else bookmark.text,
    )
    return True


def get_saved_ids(output_path: Path) -> Set[str]:
    """
    Get the set of tweet IDs already saved in the output file.

    Used to pre-populate the seen_ids set so we skip already-saved
    bookmarks on re-runs.

    Args:
        output_path: Path to the output JSON file.

    Returns:
        Set of tweet_id strings.
    """
    bookmarks = load_bookmarks(output_path)
    return {b.tweet_id for b in bookmarks}


def load_bookmarks(output_path: Path) -> List[Bookmark]:
    """
    Load bookmarks from a JSON file.

    Args:
        output_path: Path to the JSON file.

    Returns:
        List of Bookmark objects, or empty list if file doesn't exist.
    """
    if not output_path.exists():
        logger.debug("No existing bookmarks file at {}", output_path)
        return []

    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
        bookmarks = [Bookmark(**item) for item in data]
        logger.info("Loaded {} existing bookmarks from {}", len(bookmarks), output_path)
        return bookmarks
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to load existing bookmarks ({}). Starting fresh.", exc)
        return []


def _write_bookmarks(bookmarks: List[Bookmark], output_path: Path) -> None:
    """Write bookmark list to JSON file (internal helper)."""
    data = [b.model_dump() for b in bookmarks]
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
