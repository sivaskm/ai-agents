# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

X (Twitter) Bookmarks Scraper — a production-quality Python automation tool that extracts bookmarked tweets using Playwright. The scraper supports two modes:

- **Incremental mode** (default): Only processes new bookmarks since the last run by stopping when it hits a previously processed tweet ID. Daily runs typically take 5–30 seconds.
- **Historical mode**: Deep archive scraping that can resume from interruptions using checkpoint markers.

## Common Commands

### Development Setup
```bash
# Install dependencies
uv sync

# Install Playwright browsers
uv run python -m playwright install chromium
```

### Running the Scraper
```bash
# Default incremental run (scrapes only new bookmarks)
uv run python main.py

# Historical mode (deep archive scraping)
uv run python main.py --mode historical

# Quick test run with limit
uv run python main.py --max-tweets 10

# Headless mode (background)
uv run python main.py --headless

# Full scan (ignore previous state)
uv run python main.py --full-scan
```

### Testing
```bash
# Run all tests
uv run python -m pytest tests/ -v

# Run specific test file
uv run python -m pytest tests/test_bookmark_model.py -v

# Run with coverage
uv run python -m pytest tests/ --cov=.
```

## Architecture

### Core Design Pattern

The scraper uses a **click-into-tweet strategy** for data extraction:

1. **Scroll loop**: Collect visible tweet links from bookmarks page
2. **Click-through**: Navigate to each tweet's detail page for full content
3. **Thread detection**: Automatically unroll consecutive same-author tweets
4. **Immediate save**: Append each bookmark immediately to prevent data loss
5. **Incremental stop**: Halt when hitting a previously processed tweet ID

### Key Components

- **main.py**: Orchestration loop with CLI argument parsing and mode selection
- **browser/**: Playwright lifecycle management (BrowserManager) and session persistence (session_manager)
- **auth/**: Interactive login flow with encrypted credential caching (login_handler, credential_manager)
- **navigation/**: Bookmarks page navigation and infinite scroll system (bookmarks_page, scroll_manager)
- **extractor/**: Tweet data extraction with thread unrolling and link normalization (tweet_extractor)
- **storage/**: Pydantic data models (bookmark_model) and JSON file storage with deduplication (json_store)
- **state/**: Scraper state persistence for incremental/historical modes (scraper_state)
- **utils/**: Logging setup (logger), Pydantic settings from .env (config), async retry decorator (retry)

### State Management

The scraper maintains two separate state files in `state/`:

- **incremental_state.json**: Tracks `latest_tweet_id` (newest tweet from last run) — used as stop marker for incremental mode
- **historical_state.json**: Tracks `last_processed_tweet_id` (most recently scraped) — used as resume marker for historical mode

State is updated after each successfully processed bookmark, enabling crash recovery.

### Thread Detection Algorithm

On tweet detail pages, the scraper:
1. Extracts the main tweet's author
2. Scans subsequent tweet elements (replies)
3. If consecutive replies are from the same author → thread detected
4. Collects all same-author tweets until author changes or no more tweets found
5. Stores thread texts in the `thread` list (main tweet text stays in `text` field)

### Link Extraction Strategy

The extractor performs multi-stage link extraction:

1. **Regex scan**: Find explicit URLs in tweet text
2. **DOM extraction**: Scan `a[href]` and `[role="link"][href]` elements
3. **Quote tweet permalinks**: Extract from nested `div[role="link"]` structures
4. **Card links**: Extract from `[data-testid="card.wrapper"]` nested anchors
5. **t.co resolution**: Navigate to shortened URLs in new tabs to get final destinations
6. **Normalization**: Remove truncated duplicates, card metadata noise, and remaining t.co links

### Data Model

Bookmark (Pydantic model):
- `tweet_id`: Primary key (Twitter Snowflake ID)
- `author`: @handle without @
- `text`: Main tweet content
- `url`: Permalink URL
- `images`: List of image URLs
- `links`: List of external destination URLs (normalized, deduplicated)
- `is_thread`: Boolean flag
- `thread`: List of thread reply texts (empty if not a thread)

## Configuration

All settings are in `.env` or environment variables:

- `HEADLESS`: Browser headless mode (default: false)
- `SCROLL_DELAY`: Seconds between scroll actions (default: 2.0)
- `MAX_SCROLL_RETRIES`: Consecutive no-new-tweet scrolls before stop (default: 5)
- `MAX_TWEETS`: Max tweets to collect per run (default: 0 = unlimited)
- `OUTPUT_FILE`: Output filename (default: bookmarks.json)
- `LOG_LEVEL`: Logging level (default: INFO)
- `MAX_RUNTIME_MINUTES`: Safety timeout for long runs (default: 30)
- `MAX_SCROLL_LOOPS`: Maximum scroll iterations (default: 100)

## Important Implementation Details

### Anti-Detection Measures

- Human-like delays (2–6s between tweet opens, 1.5–3s between scrolls)
- Realistic viewport (1920x1080) and locale (en-US)
- Chromium automation control disabled
- Random delays throughout the extraction loop

### Error Handling

- Exponential backoff retry for tweet extraction (3 attempts)
- Graceful handling of missing DOM elements
- Session persistence across runs
- Immediate bookmark saves prevent data loss

### Twitter Snowflake IDs

Tweet IDs are monotonically increasing integers. The scraper uses numeric comparison to determine tweet ordering:
- `int(tweet_id) <= int(latest_tweet_id)` → already processed (older or equal)
- This enables efficient incremental stopping without storing full history

### File Structure

```
x-bookmarks-scraper/
├── main.py                    # Entry point with CLI args and orchestration
├── browser/                   # Playwright browser lifecycle and session management
├── auth/                      # Login flow and credential management
├── navigation/                # Bookmarks page navigation and scrolling
├── extractor/                 # Tweet data extraction with thread support
├── storage/                   # Data models and JSON file storage
├── state/                     # Scraper state persistence for incremental/historical modes
├── utils/                     # Logging, config, and retry utilities
├── tests/                     # Unit tests
├── data/                      # Output directory (auto-created)
├── .env                       # Configuration
└── session.json               # Saved session cookies (auto-created)
```

## Testing Strategy

Tests are organized by component:
- `test_bookmark_model.py`: Pydantic model validation
- `test_json_store.py`: Storage layer functionality
- `test_config.py`: Configuration loading
- `test_retry.py`: Retry decorator behavior
- `test_scraper_state.py`: State persistence logic

Tests use pytest and should be run with `uv run python -m pytest tests/ -v`.