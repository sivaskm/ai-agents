"""
Unit tests for the JSON store module.

Tests save/load functionality, deduplication by tweet_id,
and handling of corrupt/missing files.
"""

import json
import pytest
from pathlib import Path

from storage.bookmark_model import Bookmark
from storage.json_store import save_bookmarks, load_bookmarks


@pytest.fixture
def sample_bookmarks():
    """Create a list of sample bookmarks for testing."""
    return [
        Bookmark(
            tweet_id="001",
            author="alice",
            text="First tweet",
            url="https://x.com/alice/status/001",
            images=["https://pbs.twimg.com/media/a.jpg"],
        ),
        Bookmark(
            tweet_id="002",
            author="bob",
            text="Second tweet",
            url="https://x.com/bob/status/002",
            images=[],
        ),
        Bookmark(
            tweet_id="003",
            author="carol",
            text="Third tweet",
            url="https://x.com/carol/status/003",
            images=["https://pbs.twimg.com/media/c1.jpg", "https://pbs.twimg.com/media/c2.jpg"],
        ),
    ]


class TestJsonStore:
    """Test suite for JSON save/load and deduplication."""

    def test_save_and_load(self, tmp_path, sample_bookmarks):
        """Saving and loading should produce identical bookmark lists."""
        output = tmp_path / "bookmarks.json"
        save_bookmarks(sample_bookmarks, output)

        loaded = load_bookmarks(output)
        assert len(loaded) == 3
        assert loaded[0].tweet_id == "001"
        assert loaded[2].author == "carol"

    def test_deduplication_on_merge(self, tmp_path, sample_bookmarks):
        """Saving overlapping bookmarks should deduplicate by tweet_id."""
        output = tmp_path / "bookmarks.json"

        # First save
        save_bookmarks(sample_bookmarks[:2], output)

        # Second save with overlap (tweet_id 002) and one new (003)
        save_bookmarks(sample_bookmarks[1:], output)

        loaded = load_bookmarks(output)
        assert len(loaded) == 3  # 001 + 002 + 003, no duplicates
        ids = {b.tweet_id for b in loaded}
        assert ids == {"001", "002", "003"}

    def test_load_nonexistent_file(self, tmp_path):
        """Loading from a non-existent file should return empty list."""
        output = tmp_path / "does_not_exist.json"
        loaded = load_bookmarks(output)
        assert loaded == []

    def test_load_corrupt_file(self, tmp_path):
        """Loading from a corrupt JSON file should return empty list gracefully."""
        output = tmp_path / "corrupt.json"
        output.write_text("not valid json{{{", encoding="utf-8")

        loaded = load_bookmarks(output)
        assert loaded == []

    def test_creates_parent_directories(self, tmp_path):
        """Saving should create parent directories if they don't exist."""
        output = tmp_path / "nested" / "deep" / "bookmarks.json"
        save_bookmarks(
            [Bookmark(tweet_id="999", author="test")],
            output,
        )
        assert output.exists()
        loaded = load_bookmarks(output)
        assert len(loaded) == 1

    def test_output_json_format(self, tmp_path, sample_bookmarks):
        """Output JSON should be properly formatted and readable."""
        output = tmp_path / "bookmarks.json"
        save_bookmarks(sample_bookmarks, output)

        raw = output.read_text(encoding="utf-8")
        data = json.loads(raw)
        assert isinstance(data, list)
        assert all("tweet_id" in item for item in data)
        assert all("images" in item for item in data)
