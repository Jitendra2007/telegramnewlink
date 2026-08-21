"""
Test direct referer across multiple real pending shortlinks from master.
"""
import asyncio, sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

BOT_RE = re.compile(r'https?://(?:t\.me|telegram\.me)/[A-Za-z0-9_]+\?start=[A-Za-z0-9_%+/=\-]+', re.I)
HINDISINK_REFERER = "https://hindisink.com/best-free-ai-tools-content-design-or-productivity/"

# Find 3 sample shortlinks from SQL
shortlinks = []
with open(r"C:\Users\tsapa\Desktop\CODEX\pure_audioverse_219_stories_master.sql", "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        m = re.search(r"'(https?://(?:urlshortx\.io|linkshortx\.in)/[^']+)'", line)
        if m and m.group(1) not in shortlinks:
            shortlinks.append(m.group(1))
            if len(shortlinks) >= 3:
                break

print(f"Testing 3 shortlinks: {shortlinks}")

async def resolve_one(context, url, idx):
    t0 = time.time()
    page = await context.new_page()
    bot_found = [None]

    def hit(u):
        m = BOT_RE.search(u)
        if m and not bot_found[0]:
            bot_found[0] = m.group(0)

    page.on("request", lambda r: hit(r.url))
    page.on("response", lambda r: hit(r.url))

    try:
        await page.goto(url, referer=HINDISINK_REFERER, wait_until="domcontentloaded", timeout=15000)
        for i in range(12):
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
            if res.get("clicked"):
                await asyncio.sleep(2.5)
                break
            await asyncio.sleep(1.0)
    except Exception as e:
        print(f"  [{idx}] Error: {e}")
    finally:
        await page.close()

    elapsed = time.time() - t0
    return bot_found[0], elapsed

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()

        for idx, url in enumerate(shortlinks, 1):
            bot, elap = await resolve_one(context, url, idx)
            if bot:
                print(f"✅ [{idx}] SOLVED in {elap:.1f}s: {url} -> {bot}")
            else:
                print(f"❌ [{idx}] FAILED in {elap:.1f}s: {url}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
