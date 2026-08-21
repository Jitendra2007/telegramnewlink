"""
Instant Multi-Step Form Submitter for Hindisink.
Submits form#fwd immediately on each step without waiting for timers.
"""
import asyncio, sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

BOT_RE = re.compile(r'https?://(?:t\.me|telegram\.me)/([A-Za-z0-9_]+)\?start=([A-Za-z0-9_%+/=\-]+)', re.IGNORECASE)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

TEST_URL = "https://UrlShortx.io/ypvGlC76"

async def main():
    start = time.time()
    print(f"=== TESTING INSTANT FORM SUBMITTER FOR {TEST_URL} ===")
    
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--no-sandbox"])
        ctx = await browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 720})
        page = await ctx.new_page()

        found_tg = None
        def hit(url):
            nonlocal found_tg
            m = BOT_RE.search(url)
            if m:
                found_tg = m.group(0)
                print(f"\n  🔥 INTERCEPTED BOT LINK: {found_tg}\n")

        page.on("request", lambda r: hit(r.url))
        page.on("response", lambda r: hit(r.url))

        print(f"Navigating to {TEST_URL} ...")
        await page.goto(TEST_URL, wait_until="commit")

        for loop in range(40):
            await asyncio.sleep(0.5)
            if found_tg:
                break
            
            cur_url = page.url
            try:
                # Check DOM for bot link
                html = await page.content()
                m = BOT_RE.search(html) or BOT_RE.search(cur_url)
                if m:
                    found_tg = m.group(0)
                    print(f"  🎉 FOUND IN DOM: {found_tg}")
                    break

                # Check if there is a form#fwd or any step form to submit immediately!
                result = await page.evaluate("""() => {
                    // Check for Telegram link on page
                    const BOT = /(?:https?:\/\/)?(?:telegram\.me|t\.me)\/[A-Za-z0-9_]+\?start=[A-Za-z0-9_%+\/=\-]+/i;
                    for (const a of document.querySelectorAll('a')) {
                        if (BOT.test(a.href||'')) return {action: 'found_anchor', href: a.href};
                    }

                    // 1. If form#fwd or form#landing exists, submit it immediately!
                    const fwd = document.querySelector('form#fwd, form#landing, form[action*="hindisink"]');
                    if (fwd && fwd.querySelector('input[name="newwpsafelink"], input[name="clickarlink"]')) {
                        HTMLFormElement.prototype.submit.call(fwd);
                        return {action: 'submitted_step_form', action_url: fwd.action};
                    }

                    // 2. If final link / button exists (on Step 4)
                    const finalA = document.querySelector('a#final, #rtg-snp21 a, .get-link, .btn-primary, .btn-success');
                    if (finalA) {
                        if (BOT.test(finalA.href||'')) return {action: 'found_final_anchor', href: finalA.href};
                        finalA.click();
                        return {action: 'clicked_final', href: finalA.href};
                    }

                    // 3. Fallback: if #go button exists, click it
                    const go = document.getElementById('go');
                    if (go && !go.classList.contains('x')) {
                        go.click();
                        return {action: 'clicked_go'};
                    }

                    return {action: 'waiting', url: location.href};
                }""")
                
                action = result.get("action") if isinstance(result, dict) else ""
                print(f"[{loop+1}] {time.time()-start:.1f}s | url={cur_url[:55]} | action={action} | {result}")
                if isinstance(result, dict) and result.get("href"):
                    found_tg = result["href"]
                    break
            except Exception as e:
                print(f"[{loop+1}] {time.time()-start:.1f}s | (navigating: {type(e).__name__})")

        elapsed = time.time() - start
        print(f"\n==========================================")
        print(f"RESULT: {found_tg} in {elapsed:.1f}s")
        print(f"==========================================")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
