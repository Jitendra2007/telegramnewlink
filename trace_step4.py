"""
Trace step 4 redirect and cookie setting with flush=True.
"""
import asyncio, sys, re, json, time
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
TEST_URL = "https://UrlShortx.io/ypvGlC76"

STEP_HELPER_JS = r"""
() => {
  const BOT = /(?:https?:\/\/)?(?:telegram\.me|t\.me)\/[A-Za-z0-9_]+\?start=[A-Za-z0-9_%+\/=\-]+/i;
  for (const a of document.querySelectorAll('a')) {
    if (BOT.test(a.href||'')) return {action: 'found_bot', link: a.href};
  }
  const finalBtn = document.querySelector('a#final, #rtg-snp21 a, .get-link');
  if (finalBtn) {
    if (BOT.test(finalBtn.href||'')) return {action: 'found_bot', link: finalBtn.href};
    finalBtn.click();
    return {action: 'clicked_final', href: finalBtn.href};
  }
  const pDone = document.getElementById('pDone');
  if (pDone && !pDone.classList.contains('x')) {
    const btn = pDone.querySelector('button, a, input[type=submit]');
    if (btn) { btn.click(); return {action: 'clicked_pDone', text: btn.innerText||btn.value}; }
  }
  const pCont = document.getElementById('pCont');
  const cont = document.getElementById('cont');
  if (pCont && !pCont.classList.contains('x') && cont) { cont.click(); return {action: 'clicked_cont'}; }
  const go = document.getElementById('go');
  if (go && !go.classList.contains('x') && go.offsetWidth > 0) { go.click(); return {action: 'clicked_go'}; }
  return {action: 'waiting'};
}
"""

async def main():
    start = time.time()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--no-sandbox"])
        ctx = await browser.new_context(user_agent=UA)
        await ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            try { document.cookie = 'hsg=done:' + Date.now() + ';path=/;max-age=180;SameSite=Lax'; } catch(e) {}
            try { sessionStorage.setItem('hsg', 'done:' + Date.now()); } catch(e) {}
        """)
        page = await ctx.new_page()

        async def on_req(req):
            if "urlshortx.io" in req.url or "hindisink" in req.url:
                post = req.post_data
                headers = await req.all_headers()
                print(f"[REQ] {req.method} {req.url} (Cookie: {headers.get('cookie', '')[:80]})", flush=True)
                if post:
                    print(f"      POST DATA: {post[:200]}", flush=True)

        async def on_resp(resp):
            headers = await resp.all_headers()
            if "set-cookie" in headers or "location" in headers:
                print(f"[RESP {resp.status}] {resp.url}", flush=True)
                if "location" in headers: print(f"      LOCATION: {headers['location']}", flush=True)
                if "set-cookie" in headers: print(f"      SET-COOKIE: {headers['set-cookie']}", flush=True)

        page.on("request", on_req)
        page.on("response", on_resp)

        print(f"Navigating to {TEST_URL}...", flush=True)
        await page.goto(TEST_URL, wait_until="commit")

        for i in range(130):
            await asyncio.sleep(1)
            try:
                res = await page.evaluate(STEP_HELPER_JS)
                act = res.get('action') if isinstance(res, dict) else ''
                print(f"[{i+1}s] ({time.time()-start:.1f}s) url={page.url[:50]} | action={act}", flush=True)
                if isinstance(res, dict) and res.get("link"):
                    print(f"\n🎉🎉🎉 BOT LINK: {res['link']}\n", flush=True)
                    break
            except:
                pass

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
