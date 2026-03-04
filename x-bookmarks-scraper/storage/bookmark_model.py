"""
Bookmark data model using Pydantic.

Defines the core data structure for extracted bookmarks with validation.
The tweet_id serves as the primary key for deduplication — it's more
reliable than URLs which may include tracking parameters.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class Bookmark(BaseModel):
    """
    A single bookmarked tweet.

    Attributes:
        tweet_id: Unique tweet identifier extracted from the URL (primary key).
        author: Twitter handle of the tweet author.
        text: Full text content of the tweet.
        url: Permalink URL to the tweet.
        images: List of image URLs embedded in the tweet.
    """

    tweet_id: str = Field(..., description="Unique tweet status ID")
    author: str = Field(default="unknown", description="Tweet author handle")
    text: str = Field(default="", description="Tweet text content")
    url: str = Field(default="", description="Permalink to the tweet")
    images: List[str] = Field(default_factory=list, description="Image URLs in the tweet")

    class Config:
        json_schema_extra = {
            "example": {
                "tweet_id": "1891239123",
                "author": "elonmusk",
                "text": "Example tweet text here",
                "url": "https://x.com/elonmusk/status/1891239123",
                "images": ["https://pbs.twimg.com/media/example.jpg"],
            }
        }
