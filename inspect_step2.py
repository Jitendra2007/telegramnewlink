"""
Inspect all forms, buttons, links, scripts on the Step 2 article page.
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

        print("Navigating to https://hindisink.com/linkedin-profile-kaise-banaye-job-ke-liye-best-guide/ ...")
        await page.goto("https://hindisink.com/linkedin-profile-kaise-banaye-job-ke-liye-best-guide/", wait_until="domcontentloaded", timeout=20000)

        data = await page.evaluate("""() => {
            const forms = Array.from(document.forms).map(f => ({
                id: f.id, name: f.name, action: f.action, method: f.method,
                inputs: Array.from(f.elements).map(e => ({name: e.name, type: e.type, value: e.value}))
            }));
            const buttons = Array.from(document.querySelectorAll('button, a.btn, input[type=submit], input[type=button], .continue_btn, .start_btn, #final, [id*=step], [class*=step], [id*=rtg]')).map(b => ({
                tag: b.tagName, id: b.id, class: b.className, text: (b.innerText || b.value || '').trim(), href: b.href || ''
            }));
            return {forms, buttons};
        }""")

        print(f"FORMS FOUND ({len(data['forms'])}):")
        for f in data['forms']:
            print(f"  - Form: id='{f['id']}' name='{f['name']}' action='{f['action']}' inputs={f['inputs']}")

        print(f"\nBUTTONS / CONTROLS FOUND ({len(data['buttons'])}):")
        for b in data['buttons']:
            print(f"  - {b}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
