"""
Test the exact links from Rise of the War God:
https://linkshortx.in/X5Ak2DNG
https://urlshortx.io/4zEB
"""
import asyncio, sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

BOT_RE = re.compile(r'https?://(?:t\.me|telegram\.me)/[A-Za-z0-9_]+\?start=[A-Za-z0-9_%+/=\-]+', re.I)
HINDISINK_REFERER = "https://hindisink.com/best-free-ai-tools-content-design-or-productivity/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

test_links = [
    "https://linkshortx.in/X5Ak2DNG",
    "https://urlshortx.io/4zEB",
    "https://linkshortx.in/b57Yk10"
]

async def resolve_one(browser, url, idx):
    t0 = time.time()
    context = await browser.new_context(user_agent=UA)
    page = await context.new_page()
    bot_found = [None]

    def hit(u):
        m = BOT_RE.search(u)
        if m and not bot_found[0]:
            bot_found[0] = m.group(0)

    page.on("request", lambda r: hit(r.url))
    page.on("response", lambda r: hit(r.url))

    print(f"[{idx}] Navigating to {url} ...", flush=True)
    try:
        await page.goto(url, referer=HINDISINK_REFERER, wait_until="domcontentloaded", timeout=18000)
        for i in range(16):
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
            print(f"    [{i+1}s] url={page.url[:45]} | gl={res}", flush=True)
            if res.get("clicked"):
                await asyncio.sleep(3.0)
                break
            await asyncio.sleep(1.0)
    except Exception as e:
        print(f"    Error: {e}", flush=True)
    finally:
        await context.close()

    elapsed = time.time() - t0
    return url, bot_found[0], elapsed

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        for i, u in enumerate(test_links, 1):
            url, bot, el = await resolve_one(browser, u, i)
            if bot:
                print(f"✅ [{i}] SOLVED in {el:.1f}s: {url} -> {bot}\n", flush=True)
            else:
                print(f"❌ [{i}] FAILED in {el:.1f}s: {url}\n", flush=True)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
