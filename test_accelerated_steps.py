"""
Test Accelerated Step Timer:
Runs the native script logic but accelerates setInterval so each step takes 2 seconds instead of 20 seconds.
"""
import asyncio, sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

BOT_RE = re.compile(r'https?://(?:t\.me|telegram\.me)/([A-Za-z0-9_]+)\?start=([A-Za-z0-9_%+/=\-]+)', re.IGNORECASE)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
TEST_URL = "https://UrlShortx.io/ypvGlC76"

INIT_ACCELERATOR = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    // Force visible so timers never pause
    Object.defineProperty(document, 'visibilityState', {get: () => 'visible', configurable: true});
    Object.defineProperty(document, 'hidden', {get: () => false, configurable: true});
    try { document.cookie = 'hsg=done:' + Date.now() + ';path=/;max-age=180;SameSite=Lax'; } catch(e) {}
    try { sessionStorage.setItem('hsg', 'done:' + Date.now()); } catch(e) {}

    // Accelerate setInterval only on hindisink (change 1400ms to 50ms)
    const _origSI = window.setInterval;
    window.setInterval = function(fn, delay, ...args) {
        // If delay is ~1400ms (hindisink countdown timer), reduce to 50ms (28x faster!)
        const fastDelay = (delay >= 1000) ? 50 : delay;
        return _origSI.call(window, fn, fastDelay, ...args);
    };
"""

FAST_RUNNER_JS = r"""
() => {
  const BOT = /(?:https?:\/\/)?(?:telegram\.me|t\.me)\/[A-Za-z0-9_]+\?start=[A-Za-z0-9_%+\/=\-]+/i;
  for (const a of document.querySelectorAll('a')) {
    if (BOT.test(a.href||'')) return {action: 'found_bot', link: a.href};
  }
  const bt = (document.body||{}).innerText||'';
  const tm = bt.match(BOT);
  if (tm) return {action: 'found_bot', link: tm[0]};

  // 1. Final button on Step 4
  const finalBtn = document.querySelector('a#final, #rtg-snp21 a, .get-link');
  if (finalBtn) {
    if (BOT.test(finalBtn.href||'')) return {action: 'found_bot', link: finalBtn.href};
    finalBtn.click();
    return {action: 'clicked_final', href: finalBtn.href};
  }

  // 2. Go to next step (pDone)
  const pDone = document.getElementById('pDone');
  if (pDone && !pDone.classList.contains('x')) {
    const btn = pDone.querySelector('button, a, input[type=submit]');
    if (btn) {
      btn.click();
      return {action: 'clicked_pDone', text: btn.innerText||btn.value};
    }
  }

  // 3. Continue button (pCont)
  const pCont = document.getElementById('pCont');
  const cont = document.getElementById('cont');
  if (pCont && !pCont.classList.contains('x') && cont) {
    cont.click();
    return {action: 'clicked_cont'};
  }

  // 4. Click here to verify (#go)
  const go = document.getElementById('go');
  if (go && !go.classList.contains('x') && go.offsetWidth > 0 && go.offsetHeight > 0) {
    go.click();
    return {action: 'clicked_go'};
  }

  return {action: 'waiting', url: location.href};
}
"""

async def main():
    start = time.time()
    print(f"=== TESTING ACCELERATED RESOLUTION (50ms interval) FOR {TEST_URL} ===")
    
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        ctx = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 720}
        )
        await ctx.add_init_script(INIT_ACCELERATOR)

        page = await ctx.new_page()

        found_tg = None
        def hit(url):
            nonlocal found_tg
            m = BOT_RE.search(url)
            if m and not found_tg:
                found_tg = m.group(0)
                print(f"\n  🔥 INTERCEPTED BOT LINK: {found_tg}\n", flush=True)

        page.on("request", lambda r: hit(r.url))
        page.on("response", lambda r: hit(r.url))

        print(f"Navigating to {TEST_URL} ...", flush=True)
        await page.goto(TEST_URL, wait_until="commit")

        for loop in range(60):  # max 30s
            await asyncio.sleep(0.5)
            if found_tg:
                break
            
            cur_url = page.url
            try:
                html = await page.content()
                m = BOT_RE.search(html) or BOT_RE.search(cur_url)
                if m:
                    found_tg = m.group(0)
                    print(f"  🎉 FOUND IN DOM: {found_tg}", flush=True)
                    break

                res = await page.evaluate(FAST_RUNNER_JS)
                act = res.get("action") if isinstance(res, dict) else ""
                print(f"[{loop+1}] {time.time()-start:.1f}s | url={cur_url[:45]} | action={act}", flush=True)
                if isinstance(res, dict) and res.get("link"):
                    found_tg = res["link"]
                    break
            except Exception as e:
                print(f"[{loop+1}] {time.time()-start:.1f}s | (navigating: {type(e).__name__})", flush=True)

        elapsed = time.time() - start
        print(f"\n==========================================")
        print(f"RESULT: {found_tg} in {elapsed:.1f}s")
        print(f"==========================================")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
