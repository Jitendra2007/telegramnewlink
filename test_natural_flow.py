"""
Natural timer flow tester: Lets each step run its natural timer (~15s) and clicks when ready.
"""
import asyncio, sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

BOT_RE = re.compile(r'https?://(?:t\.me|telegram\.me)/([A-Za-z0-9_]+)\?start=([A-Za-z0-9_%+/=\-]+)', re.IGNORECASE)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
TEST_URL = "https://UrlShortx.io/ypvGlC76"

NATURAL_STEP_JS = r"""
() => {
  const BOT = /(?:https?:\/\/)?(?:telegram\.me|t\.me)\/[A-Za-z0-9_]+\?start=[A-Za-z0-9_%+\/=\-]+/i;
  for (const a of document.querySelectorAll('a')) {
    if (BOT.test(a.href||'')) return {action: 'found_bot', link: a.href};
  }
  const bt = (document.body||{}).innerText||'';
  const tm = bt.match(BOT);
  if (tm) return {action: 'found_bot', link: tm[0]};

  // 1. If final link / button on Step 4 is ready
  const finalBtn = document.querySelector('a#final, #rtg-snp21 a, .get-link');
  if (finalBtn) {
    if (BOT.test(finalBtn.href||'')) return {action: 'found_bot', link: finalBtn.href};
    finalBtn.click();
    return {action: 'clicked_final', href: finalBtn.href};
  }

  // 2. If pDone (Go to next step) is visible and NOT hidden by class 'x'
  const pDone = document.getElementById('pDone');
  if (pDone && !pDone.classList.contains('x')) {
    const btn = pDone.querySelector('button, a, input[type=submit]');
    if (btn) {
      btn.click();
      return {action: 'clicked_pDone', text: btn.innerText||btn.value};
    }
  }

  // 3. If pCont (Continue) is visible and NOT hidden by class 'x'
  const pCont = document.getElementById('pCont');
  const cont = document.getElementById('cont');
  if (pCont && !pCont.classList.contains('x') && cont) {
    cont.click();
    return {action: 'clicked_cont'};
  }

  // 4. If #go ('Click here to verify') is visible and NOT clicked yet
  const go = document.getElementById('go');
  if (go && !go.classList.contains('x') && go.offsetWidth > 0 && go.offsetHeight > 0) {
    go.click();
    return {action: 'clicked_go'};
  }

  // 5. If countdown timer is currently running
  const cd = document.getElementById('cd');
  if (cd && !cd.classList.contains('x')) {
    const num = (document.getElementById('num') || {}).innerText || '';
    return {action: 'timer_countdown', seconds_left: num};
  }

  // 6. If hold timer (5s) is currently running
  const pHold = document.getElementById('pHold');
  if (pHold && !pHold.classList.contains('x')) {
    const hold = (document.getElementById('hold') || {}).innerText || '';
    return {action: 'timer_hold', status: hold};
  }

  return {action: 'waiting', url: location.href};
}
"""

async def main():
    start = time.time()
    print(f"=== TESTING NATURAL RESOLVER FLOW FOR {TEST_URL} ===")
    
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        ctx = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 720}
        )
        
        # Pre-set hsg gate bypass so user doesn't need to click ads
        await ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            try { document.cookie = 'hsg=done:' + Date.now() + ';path=/;max-age=180;SameSite=Lax'; } catch(e) {}
            try { sessionStorage.setItem('hsg', 'done:' + Date.now()); } catch(e) {}
        """)

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

        for loop in range(120):  # max 2 minutes
            await asyncio.sleep(1.0)
            if found_tg:
                break
            
            cur_url = page.url
            try:
                # Check DOM
                html = await page.content()
                m = BOT_RE.search(html) or BOT_RE.search(cur_url)
                if m:
                    found_tg = m.group(0)
                    print(f"  🎉 FOUND IN DOM: {found_tg}")
                    break

                res = await page.evaluate(NATURAL_STEP_JS)
                act = res.get("action") if isinstance(res, dict) else ""
                print(f"[{loop+1}s] ({time.time()-start:.1f}s) url={cur_url[:50]} | action={act} | {res}")
                if isinstance(res, dict) and res.get("link"):
                    found_tg = res["link"]
                    break
            except Exception as e:
                print(f"[{loop+1}s] ({time.time()-start:.1f}s) | (navigating: {type(e).__name__})")

        elapsed = time.time() - start
        print(f"\n==========================================")
        print(f"FINAL RESULT: {found_tg} in {elapsed:.1f}s")
        print(f"==========================================")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
