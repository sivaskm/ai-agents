import asyncio
from browser.browser_manager import BrowserManager
from browser.session_manager import load_session
from loguru import logger
import sys

logger.remove()
logger.add(sys.stdout, level="DEBUG")

async def main():
    logger.info("Starting layout analysis script")
    async with BrowserManager(headless=False) as browser:
        page = browser.page
        context = browser.context
        
        await load_session(context)
        
        url = "https://x.com/KrishXCodes/status/2029148869649691086"
        logger.info("Navigating to {}", url)
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        
        await page.wait_for_timeout(3000)
        
        # Scroll to load the full thread
        for _ in range(10):
            await page.evaluate("window.scrollBy(0, 800)")
            await page.wait_for_timeout(1000)
            
        tweets = page.locator('[data-testid="tweet"]')
        count = await tweets.count()
        logger.info("Found {} tweets in DOM", count)
        
        for i in range(count):
            tweet = tweets.nth(i)
            text = await tweet.inner_text()
            if "If you’re trying to break into tech" in text or "If you're trying to break into tech" in text:
                logger.info("Found target tweet index {}!", i)
                html = await tweet.evaluate("el => el.innerHTML")
                with open("tweet_html.txt", "w", encoding="utf-8") as f:
                    f.write(html)
                logger.info("Saved HTML to tweet_html.txt")
                break

if __name__ == "__main__":
    asyncio.run(main())
