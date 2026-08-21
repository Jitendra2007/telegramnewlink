"""
Inspect full HTML of Step 1 and inspect all hidden inputs, forms, and scripts once .steps is loaded.
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

        print("Navigating to https://UrlShortx.io/ypvGlC76 ...")
        await page.goto("https://UrlShortx.io/ypvGlC76", wait_until="commit")

        # Wait until we land on a page with .steps
        for i in range(25):
            await asyncio.sleep(1)
            try:
                has_steps = await page.evaluate("() => !!document.querySelector('.steps')")
                print(f"[{i+1}s] url={page.url} | has_steps={has_steps}")
                if has_steps:
                    break
            except:
                pass
        
        print(f"\nFinal URL with steps: {page.url}")
        
        # Extract all forms, hidden fields, and scripts
        data = await page.evaluate("""() => {
            const forms = Array.from(document.forms).map(f => ({
                id: f.id, name: f.name, action: f.action, method: f.method,
                outerHTML: f.outerHTML
            }));
            const inlineScripts = Array.from(document.querySelectorAll('script:not([src])')).map(s => s.textContent);
            return {forms, inlineScripts};
        }""")

        print(f"\n--- FORMS ON STEP 1 ({len(data['forms'])}) ---")
        for f in data['forms']:
            print(f"FORM: id={f['id']} action={f['action']} method={f['method']}")
            print(f"{f['outerHTML']}\n")

        print(f"\n--- INLINE SCRIPTS ({len(data['inlineScripts'])}) ---")
        for s in data['inlineScripts']:
            if len(s.strip()) > 20:
                print(f"--- SCRIPT ---\n{s[:1000]}\n")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
