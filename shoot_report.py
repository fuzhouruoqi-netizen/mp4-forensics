import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent


async def main():
    url = (ROOT / "samples" / "report.html").as_uri()
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="msedge", headless=True)
        page = await b.new_page(viewport={"width": 1000, "height": 1400}, device_scale_factor=2)
        await page.goto(url, wait_until="networkidle")
        await page.screenshot(path=str(ROOT / "samples" / "report.png"), full_page=True)
        await b.close()
    print("ok")


asyncio.run(main())
