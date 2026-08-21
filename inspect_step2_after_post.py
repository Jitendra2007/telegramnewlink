"""
Capture HTML on Step 2 after Step 1 POST.
"""
import asyncio, sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
TEST_URL = "https://UrlShortx.io/ypvGlC76"

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--no-sandbox"])
        ctx = await browser.new_context(user_agent=UA)
        page = await ctx.new_page()

        print(f"Navigating to {TEST_URL} ...")
        await page.goto(TEST_URL, wait_until="commit")

        step2_captured = False

        for i in range(25):
            await asyncio.sleep(1)
            cur = page.url
            print(f"[{i+1}s] url={cur[:60]}")
            
            # If on step 1, submit form#fwd immediately
            if not step2_captured:
                try:
                    fwd = await page.query_selector("form#fwd, form#landing")
                    if fwd:
                        print("  Submitting Step 1 form...")
                        await page.evaluate("() => HTMLFormElement.prototype.submit.call(document.querySelector('form#fwd, form#landing'))")
                        step2_captured = True
                        await asyncio.sleep(2)
                        continue
                except:
                    pass
            else:
                # We are on Step 2! Let's inspect everything on Step 2
                html = await page.content()
                print(f"\n--- STEP 2 HTML SNIPPET (len={len(html)}) ---")
                forms = await page.evaluate("""() => {
                    const forms = Array.from(document.forms).map(f => ({id: f.id, action: f.action, method: f.method, html: f.outerHTML}));
                    const buttons = Array.from(document.querySelectorAll('button, a, input')).map(b => ({
                        id: b.id, class: b.className, text: (b.innerText || b.value || '').trim()
                    })).filter(b => b.text.length > 0);
                    const steps = (document.querySelector('.steps') || {}).outerHTML || 'NO_STEPS';
                    return {forms, buttons: buttons.slice(0, 10), steps};
                }""")
                print(f"Forms on Step 2: {forms.get('forms')}")
                print(f"Buttons on Step 2: {forms.get('buttons')}")
                print(f"Steps on Step 2: {forms.get('steps')}")

                # Save full Step 2 HTML to inspect
                with open("step2_page.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("Saved step2_page.html")
                break

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
