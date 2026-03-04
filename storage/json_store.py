"""
JSON file storage for bookmarks.

Provides save/load functionality with deduplication by tweet_id.
Ensures the data directory exists and handles merging new bookmarks
with previously saved ones to support incremental scraping sessions.
"""

import json
from pathlib import Path
from typing import List

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
    # Ensure the output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing bookmarks for merge
    existing = load_bookmarks(output_path)
    existing_ids = {b.tweet_id for b in existing}

    # Merge: add only new bookmarks
    new_count = 0
    for bookmark in bookmarks:
        if bookmark.tweet_id not in existing_ids:
            existing.append(bookmark)
            existing_ids.add(bookmark.tweet_id)
            new_count += 1

    # Serialize and write
    data = [b.model_dump() for b in existing]
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info(
        "Saved {} bookmarks ({} new, {} existing) to {}",
        len(existing),
        new_count,
        len(existing) - new_count,
        output_path,
    )


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
