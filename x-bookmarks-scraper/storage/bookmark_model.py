"""
Bookmark data model using Pydantic.

Defines the core data structure for extracted bookmarks with validation.
The tweet_id serves as the primary key for deduplication. Supports both
single tweets and threads (a series of tweets by the same author).
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class Bookmark(BaseModel):
    """
    A single bookmarked tweet, with optional thread content.

    Attributes:
        tweet_id: Unique tweet identifier extracted from the URL (primary key).
        author: Twitter handle of the tweet author.
        text: Full text content of the main tweet.
        url: Permalink URL to the tweet.
        images: List of image URLs embedded in the tweet.
        is_thread: Whether the bookmark is a thread (multiple tweets by same author).
        thread: List of text content for each tweet in the thread (if is_thread).
    """

    tweet_id: str = Field(..., description="Unique tweet status ID")
    author: str = Field(default="unknown", description="Tweet author handle")
    text: str = Field(default="", description="Tweet text content")
    url: str = Field(default="", description="Permalink to the tweet")
    images: List[str] = Field(default_factory=list, description="Image URLs in the tweet")
    is_thread: bool = Field(default=False, description="Whether this is a thread")
    thread: List[str] = Field(default_factory=list, description="Thread tweet texts in order")

    class Config:
        json_schema_extra = {
            "example": {
                "tweet_id": "1891239123",
                "author": "elonmusk",
                "text": "Example tweet text here",
                "url": "https://x.com/elonmusk/status/1891239123",
                "images": ["https://pbs.twimg.com/media/example.jpg"],
                "is_thread": True,
                "thread": [
                    "First tweet in thread",
                    "Second tweet continues the story",
                    "Third tweet wraps up",
                ],
            }
        }
