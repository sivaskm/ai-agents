# X (Twitter) Bookmarks Scraper

A production-quality Python automation tool that extracts your bookmarked tweets from X (Twitter) using Playwright.

## Features

- 🔐 **Session persistence** — login once, reuse cookies on subsequent runs
- 📜 **Infinite scroll** — automatically loads all bookmarks using scroll-into-view strategy
- 🧠 **Smart deduplication** — uses tweet ID as primary key, merges with existing data
- 🖼️ **Image extraction** — captures media URLs from tweets
- 🔄 **Retry logic** — exponential backoff for resilient network operations
- 📊 **Structured logging** — console + rotating file logs via Loguru
- ⚙️ **CLI arguments** — customize max tweets, headless mode, output file
- 🛡️ **Anti-detection** — human-like delays and realistic browser fingerprint

## Quick Start

### 1. Install uv

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. Install dependencies

```bash
uv sync
```

### 3. Install Playwright browsers

```bash
uv run python -m playwright install chromium
```

### 4. Run the scraper

```bash
# Default — opens browser, scrapes all bookmarks
uv run python main.py

# Limit to 100 tweets
uv run python main.py --max-tweets 100

# Headless mode with custom output
uv run python main.py --headless --output-file export.json
```

## First Run

On the first run (no `session.json`), the scraper will:

1. Open a Chromium browser
2. Prompt you for your X username/email and password in the terminal
3. Perform automated login
4. Save session cookies to `session.json`

On subsequent runs, it will reuse the saved session.

## Project Structure

```
x-bookmarks-scraper/
├── main.py                        # Entry point with CLI args
├── browser/
│   ├── browser_manager.py         # Playwright browser lifecycle
│   └── session_manager.py         # Cookie persistence & login detection
├── auth/
│   └── login_handler.py           # Interactive login flow
├── navigation/
│   ├── bookmarks_page.py          # Bookmarks page navigation
│   └── scroll_manager.py          # Infinite scroll system
├── extractor/
│   └── tweet_extractor.py         # Tweet data extraction (text, author, URL, images)
├── storage/
│   ├── bookmark_model.py          # Pydantic data model
│   └── json_store.py              # JSON file storage with dedup
├── utils/
│   ├── logger.py                  # Loguru logging setup
│   ├── config.py                  # Pydantic settings from .env
│   └── retry.py                   # Async retry decorator
├── tests/                         # Unit tests
├── data/                          # Output directory (auto-created)
│   └── bookmarks.json
├── .env                           # Configuration
└── session.json                   # Saved session (auto-created)
```

## Configuration

All settings can be configured via `.env` file or environment variables:

| Variable | Default | Description |
|---|---|---|
| `HEADLESS` | `false` | Run browser headlessly |
| `SCROLL_DELAY` | `2.0` | Seconds between scroll actions |
| `MAX_SCROLL_RETRIES` | `5` | Consecutive no-new-tweet scrolls before stop |
| `MAX_TWEETS` | `0` | Max tweets to collect (0 = unlimited) |
| `OUTPUT_FILE` | `bookmarks.json` | Output filename |
| `LOG_LEVEL` | `INFO` | Logging level |

## Output Format

```json
[
  {
    "tweet_id": "1891239123",
    "author": "username",
    "text": "Tweet content here",
    "url": "https://x.com/username/status/1891239123",
    "images": ["https://pbs.twimg.com/media/example.jpg"]
  }
]
```

## Running Tests

```bash
uv run python -m pytest tests/ -v
```

## License

MIT
