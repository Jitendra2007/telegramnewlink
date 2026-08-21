"""
Inspect why chrome-error://chromewebdata/ happens.
"""
import asyncio, sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        ctx = await browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 720})
        page = await ctx.new_page()

        page.on("requestfailed", lambda req: print(f"  ❌ FAILED REQ: {req.url} -> {req.failure}"))
        page.on("framenavigated", lambda frame: print(f"  🧭 NAVIGATED: {frame.url}"))

        try:
            print("Going to https://UrlShortx.io/ypvGlC76 ...")
            await page.goto("https://UrlShortx.io/ypvGlC76", wait_until="commit", timeout=20000)
            
            for i in range(25):
                await asyncio.sleep(1)
                cur = page.url
                print(f"[{i+1}s] url = {cur}")
                if "chrome-error" in cur:
                    content = await page.content()
                    print(f"Error page content snippet: {content[:500]}")
                    break
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
