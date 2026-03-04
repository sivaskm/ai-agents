"""
Unit tests for the Bookmark model.

Validates Pydantic model construction, defaults, and validation behavior.
"""

import pytest
from storage.bookmark_model import Bookmark


class TestBookmarkModel:
    """Test suite for the Bookmark Pydantic model."""

    def test_valid_bookmark_full(self):
        """A fully populated bookmark should validate correctly."""
        bookmark = Bookmark(
            tweet_id="1234567890",
            author="testuser",
            text="Hello world!",
            url="https://x.com/testuser/status/1234567890",
            images=["https://pbs.twimg.com/media/example.jpg"],
        )
        assert bookmark.tweet_id == "1234567890"
        assert bookmark.author == "testuser"
        assert bookmark.text == "Hello world!"
        assert bookmark.url == "https://x.com/testuser/status/1234567890"
        assert len(bookmark.images) == 1

    def test_valid_bookmark_minimal(self):
        """A bookmark with only the required tweet_id should use defaults."""
        bookmark = Bookmark(tweet_id="999")
        assert bookmark.tweet_id == "999"
        assert bookmark.author == "unknown"
        assert bookmark.text == ""
        assert bookmark.url == ""
        assert bookmark.images == []

    def test_missing_tweet_id_raises(self):
        """tweet_id is required and should raise ValidationError if missing."""
        with pytest.raises(Exception):
            Bookmark(author="user", text="test")

    def test_multiple_images(self):
        """A bookmark can have multiple images."""
        bookmark = Bookmark(
            tweet_id="123",
            images=[
                "https://pbs.twimg.com/media/a.jpg",
                "https://pbs.twimg.com/media/b.jpg",
                "https://pbs.twimg.com/media/c.jpg",
            ],
        )
        assert len(bookmark.images) == 3

    def test_serialization_roundtrip(self):
        """model_dump and re-construction should produce identical objects."""
        original = Bookmark(
            tweet_id="555",
            author="alice",
            text="Roundtrip test",
            url="https://x.com/alice/status/555",
            images=["https://pbs.twimg.com/media/test.jpg"],
        )
        data = original.model_dump()
        restored = Bookmark(**data)
        assert original == restored

    def test_json_serialization(self):
        """model_dump_json should produce valid JSON string."""
        bookmark = Bookmark(tweet_id="789", author="bob")
        json_str = bookmark.model_dump_json()
        assert '"tweet_id":"789"' in json_str.replace(" ", "")
        assert '"author":"bob"' in json_str.replace(" ", "")
