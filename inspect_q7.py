"""
Inspect q7m4vk29.php and the Step 1 / Step 2 forms in detail.
"""
import asyncio, sys, re, json
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--no-sandbox"])
        ctx = await browser.new_context(user_agent=UA)
        page = await ctx.new_page()

        print("Navigating to https://hindisink.com/q7m4vk29.php?id=https://urlshortx.io/ypvGlC76 ...")
        resp = await page.goto("https://hindisink.com/q7m4vk29.php?id=https://urlshortx.io/ypvGlC76", wait_until="commit")
        
        content = await page.content()
        print("\n--- CONTENT of q7m4vk29.php ---")
        print(content)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
