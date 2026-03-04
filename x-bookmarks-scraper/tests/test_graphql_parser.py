import json
from pathlib import Path

from extractor.graphql_parser import parse_bookmarks_response


def test_parse_graphql_bookmarks_from_sample():
    """Verify the new parser extracts cleanly from a real API response."""
    sample_path = Path("/tmp/graphql_responses.json")
    if not sample_path.exists():
        # Skip if running in CI without the captured payload
        return
        
    with open(sample_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    payload = data[0]["body"]
    
    # Run the parser
    bookmarks, cursor = parse_bookmarks_response(payload)
    
    # We saw 20 bookmarks in the 22 entries
    assert len(bookmarks) == 20
    assert cursor is not None
    assert cursor.startswith("HBa")
    
    # Check the first bookmark
    first = bookmarks[0]
    assert first.tweet_id == "2029148869649691086"
    assert "2 years ago I had no real experience" in first.text
    assert first.author is not None
    assert first.url == f"https://x.com/{first.author}/status/{first.tweet_id}"
    
    # Check a tweet with proper links (e.g. index 1)
    # The second tweet in the payload should have an openai link
    t2 = bookmarks[1]
    assert "openai.com" in " ".join(t2.links)
    
    # Ensure none of them contain '…' in the links
    for b in bookmarks:
        for l in b.links:
            assert not l.endswith("…"), f"Truncated link found: {l}"
            assert "t.co/" not in l, f"Unresolved t.co link found: {l}"

