"""
Inspect hindisink.com article page DOM and automate the full steps to bot link.
"""
import asyncio, sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

BOT_RE = re.compile(r'https?://(?:t\.me|telegram\.me)/([A-Za-z0-9_]+)\?start=([A-Za-z0-9_%+/=\-]+)', re.IGNORECASE)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        ctx = await browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 720})
        page = await ctx.new_page()

        found_tg = None
        def hit(url):
            nonlocal found_tg
            m = BOT_RE.search(url)
            if m:
                found_tg = m.group(0)
                print(f"  🔥 INTERCEPTED BOT LINK: {found_tg}")

        page.on("request", lambda r: hit(r.url))
        page.on("response", lambda r: hit(r.url))

        print("Navigating to https://UrlShortx.io/ypvGlC76 ...")
        await page.goto("https://UrlShortx.io/ypvGlC76", wait_until="commit", timeout=20000)

        for step in range(35):
            await asyncio.sleep(1)
            if found_tg:
                break
            try:
                cur = page.url
                html = await page.content()
                m = BOT_RE.search(html) or BOT_RE.search(cur)
                if m:
                    found_tg = m.group(0)
                    print(f"  🎉 FOUND IN DOM: {m.group(0)}")
                    break

                # Inspect elements on current page
                info = await page.evaluate("""() => {
                    const forms = Array.from(document.querySelectorAll('form')).map(f => ({id: f.id, action: f.action, name: f.name}));
                    const buttons = Array.from(document.querySelectorAll('button, a.btn, input[type=submit], input[type=button]')).map(b => ({
                        tag: b.tagName, id: b.id, class: b.className, text: (b.innerText || b.value || '').trim(), href: b.href || ''
                    })).filter(b => b.text.length > 0);
                    const hsg = !!document.getElementById('hsg');
                    const steps = (document.querySelector('.steps') || {}).outerHTML || '';
                    return {forms, buttons: buttons.slice(0, 8), hsg, steps: steps.substring(0, 200)};
                }""")
                print(f"[{step+1}s] url={cur[:60]} | hsg={info.get('hsg')} | forms={len(info.get('forms',[]))} | btns={[b['text'] for b in info.get('buttons',[])]}")
            except Exception as e:
                print(f"[{step+1}s] (navigating/busy: {type(e).__name__})")

        print(f"\n==========================================")
        print(f"FINAL RESULT: {found_tg}")
        print(f"==========================================")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
