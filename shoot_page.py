import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright


async def main():
    src = Path(r"D:\Users\杨子晗\Documents\deepseek-harness\default-workspace\mp4-forensics\docs\index.html")
    out = Path(r"D:\Users\杨子晗\Documents\deepseek-harness\default-workspace\mp4-forensics\docs\preview.png")
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="msedge", headless=True)
        page = await b.new_page(viewport={"width": 1280, "height": 1000}, device_scale_factor=1)
        await page.goto(src.as_uri(), wait_until="networkidle")
        await page.screenshot(path=str(out), full_page=True)
        await b.close()
    print("ok", out)


asyncio.run(main())
