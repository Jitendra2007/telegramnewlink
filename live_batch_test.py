"""
Live Batch Test with Isolated Contexts:
Each worker gets its own isolated browser context so cookies never collide.
"""
import asyncio, sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

BOT_RE = re.compile(r'https?://(?:t\.me|telegram\.me)/[A-Za-z0-9_]+\?start=[A-Za-z0-9_%+/=\-]+', re.I)
HINDISINK_REFERER = "https://hindisink.com/best-free-ai-tools-content-design-or-productivity/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

test_links = [
    "https://linkshortx.in/asL8",
    "https://urlshortx.io/XUYHpR3",
    "https://linkshortx.in/E6XHZcEO",
    "https://linkshortx.in/eaPALb",
    "https://urlshortx.io/dLaV7sTF"
]

async def resolve_worker(browser, shortlink: str, worker_id: int):
    t0 = time.time()
    # ISOLATED CONTEXT per worker!
    context = await browser.new_context(user_agent=UA)
    page = await context.new_page()
    bot_found = [None]

    def hit(u):
        m = BOT_RE.search(u)
        if m and not bot_found[0]:
            bot_found[0] = m.group(0)

    page.on("request", lambda r: hit(r.url))
    page.on("response", lambda r: hit(r.url))

    try:
        await page.goto(shortlink, referer=HINDISINK_REFERER, wait_until="domcontentloaded", timeout=18000)
        for i in range(16):
            if bot_found[0]:
                break
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
            if res.get("clicked"):
                await asyncio.sleep(2.5)
                break
            await asyncio.sleep(1.0)
    except Exception as e:
        pass
    finally:
        await context.close()

    elapsed = time.time() - t0
    return shortlink, bot_found[0], elapsed

async def main():
    print(f"==================================================")
    print(f"🚀 RUNNING ISOLATED BATCH TEST ON {len(test_links)} LINKS")
    print(f"==================================================")
    
    t_start = time.time()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox"])

        tasks = [resolve_worker(browser, link, i+1) for i, link in enumerate(test_links)]
        results = await asyncio.gather(*tasks)

        total_time = time.time() - t_start
        print(f"\n==================== RESULTS ====================")
        success = 0
        for i, (link, bot, el) in enumerate(results, 1):
            if bot:
                success += 1
                print(f"✅ [{i}] ({el:.1f}s) {link}\n    -> {bot}\n")
            else:
                print(f"❌ [{i}] ({el:.1f}s) {link} (FAILED)\n")

        print(f"🎯 SUMMARY: {success}/{len(test_links)} SUCCESSFUL in {total_time:.1f}s total!")
        print(f"⚡ EFFECTIVE SPEED: {total_time/len(test_links):.2f} seconds per link!")
        print(f"==================================================")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
