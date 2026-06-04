import asyncio
import os
from pathlib import Path

async def capture_screenshot_async(url: str, output_path: str, retries: int = 5, delay: float = 2.0) -> bool:
    """Capture a screenshot of the given URL using Playwright headless Chromium."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[Nexo] Playwright not installed. Run: pip install playwright && playwright install chromium")
        return False

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            device_scale_factor=2  # Retina / high-DPI
        )
        page = await context.new_page()

        for attempt in range(retries):
            try:
                await page.goto(url, wait_until="networkidle", timeout=15000)
                await asyncio.sleep(1.5)  # Extra settle time
                await page.screenshot(path=output_path, full_page=False, type="png")
                print(f"[Nexo] Screenshot saved → {output_path}")
                await browser.close()
                return True
            except Exception as e:
                print(f"[Nexo] Screenshot attempt {attempt + 1}/{retries} failed: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(delay)

        await browser.close()
        return False


def capture_screenshot(url: str, output_path: str) -> bool:
    """Sync wrapper around the async screenshot capture."""
    return asyncio.run(capture_screenshot_async(url, output_path))


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        url = sys.argv[1]
        out = sys.argv[2]
        success = capture_screenshot(url, out)
        sys.exit(0 if success else 1)
