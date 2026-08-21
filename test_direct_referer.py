"""
Test Phase 1 Direct Referer vs Phase 2 Fallback on live links.
"""
import asyncio, sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

BOT_RE = re.compile(r'https?://(?:t\.me|telegram\.me)/[A-Za-z0-9_]+\?start=[A-Za-z0-9_%+/=\-]+', re.I)
HINDISINK_REFERER = "https://hindisink.com/best-free-ai-tools-content-design-or-productivity/"
TEST_URL = "https://UrlShortx.io/ypvGlC76"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        bot_found = [None]
        def hit(url):
            m = BOT_RE.search(url)
            if m and not bot_found[0]:
                bot_found[0] = m.group(0)

        page.on("request", lambda r: hit(r.url))
        page.on("response", lambda r: hit(r.url))

        print(f"Testing direct referer: {TEST_URL} with referer={HINDISINK_REFERER}...")
        t0 = time.time()
        try:
            await page.goto(TEST_URL, referer=HINDISINK_REFERER, wait_until="domcontentloaded", timeout=15000)
            for i in range(8):
                if bot_found[0]: break
                res = await page.evaluate(r"""() => {
                    const gl = document.querySelector(".get-link, #getlink, a.get-link");
                    if (!gl) return {found: false};
                    const locked = gl.classList.contains("disabled") || (gl.innerText||'').includes("wait");
                    if (!locked) {
                        try { gl.click(); } catch(e){}
                        return {clicked: true};
                    }
                    return {locked: true};
                }""")
                print(f"  [{i+1}] url={page.url[:40]} | res={res}", flush=True)
                if res.get("clicked"):
                    await asyncio.sleep(2)
                    break
                await asyncio.sleep(1)
        except Exception as e:
            print(f"  Error: {e}")

        print(f"Result: {bot_found[0]} in {time.time()-t0:.1f}s")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
