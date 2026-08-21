"""
Diagnose https://UrlShortx.io/XM841L75
"""
import asyncio, sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

BOT_RE = re.compile(r'https?://(?:t\.me|telegram\.me)/[A-Za-z0-9_]+\?start=[A-Za-z0-9_%+/=\-]+', re.I)
HINDISINK_REFERER = "https://hindisink.com/best-free-ai-tools-content-design-or-productivity/"
TEST_URL = "https://UrlShortx.io/XM841L75"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        bot_found = [None]
        def hit(u):
            m = BOT_RE.search(u)
            if m and not bot_found[0]:
                bot_found[0] = m.group(0)
                print(f"🔥 FOUND BOT LINK: {bot_found[0]}")

        page.on("request", lambda r: hit(r.url))
        page.on("response", lambda r: hit(r.url))

        print(f"Testing {TEST_URL}...")
        resp = await page.goto(TEST_URL, referer=HINDISINK_REFERER, wait_until="domcontentloaded")
        print(f"Initial status: {resp.status if resp else 'None'} url={page.url}")

        for i in range(25):
            if bot_found[0]: break
            res = await page.evaluate(r"""() => {
                const gl = document.querySelector(".get-link, #getlink, a.get-link");
                const b = document.querySelector('a#final, #rtg-snp21 a, a.btn-primary');
                return {
                    url: location.href,
                    title: document.title,
                    gl: gl ? {text: gl.innerText, disabled: gl.classList.contains('disabled')} : null,
                    b: b ? {text: b.innerText, href: b.href} : null
                };
            }""")
            print(f"[{i+1}] {res}")
            
            # Click if unlocked
            if res.get('gl') and not res['gl'].get('disabled'):
                try:
                    await page.click('.get-link', timeout=3000, force=True)
                    print("  Clicked .get-link!")
                except Exception as e:
                    print(f"  Click error: {e}")
            elif res.get('b') and res['b'].get('href'):
                if BOT_RE.search(res['b']['href']):
                    bot_found[0] = res['b']['href']
                    break
                try:
                    await page.click('a#final, #rtg-snp21 a, a.btn-primary', timeout=3000, force=True)
                except:
                    pass

            await asyncio.sleep(1.0)

        print(f"Final Bot: {bot_found[0]}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
