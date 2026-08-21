"""
Tuned Speed Test:
Tests 5.0s, 6.0s, 7.0s per-step timer to find the fastest threshold that passes server validation in 20-30s!
"""
import asyncio, sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

BOT_RE = re.compile(r'https?://(?:t\.me|telegram\.me)/([A-Za-z0-9_]+)\?start=([A-Za-z0-9_%+/=\-]+)', re.IGNORECASE)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
TEST_URL = "https://UrlShortx.io/ypvGlC76"

def get_init_script(step_interval_ms):
    return f"""
    Object.defineProperty(navigator, 'webdriver', {{get: () => undefined}});
    Object.defineProperty(document, 'visibilityState', {{get: () => 'visible', configurable: true}});
    Object.defineProperty(document, 'hidden', {{get: () => false, configurable: true}});
    try {{ document.cookie = 'hsg=done:' + Date.now() + ';path=/;max-age=180;SameSite=Lax'; }} catch(e) {{}}
    try {{ sessionStorage.setItem('hsg', 'done:' + Date.now()); }} catch(e) {{}}

    // Tune the interval so 15-count completes in exact target time
    const _origSI = window.setInterval;
    window.setInterval = function(fn, delay, ...args) {{
        const fastDelay = (delay >= 500) ? {step_interval_ms} : delay;
        return _origSI.call(window, fn, fastDelay, ...args);
    }};
    """

STEP_JS = r"""
() => {
  const BOT = /(?:https?:\/\/)?(?:telegram\.me|t\.me)\/[A-Za-z0-9_]+\?start=[A-Za-z0-9_%+\/=\-]+/i;
  for (const a of document.querySelectorAll('a')) {
    if (BOT.test(a.href||'')) return {action: 'found_bot', link: a.href};
  }
  const bt = (document.body||{}).innerText||'';
  const tm = bt.match(BOT);
  if (tm) return {action: 'found_bot', link: tm[0]};

  const gate = document.getElementById('hsg');
  if (gate) {
    gate.hidden = true;
    if (gate.parentNode) gate.parentNode.removeChild(gate);
    document.documentElement.style.overflow = '';
  }

  // Final button (Step 4 or UrlShortx)
  const finalBtn = document.querySelector('a#final, #rtg-snp21 a, .get-link');
  if (finalBtn) {
    if (BOT.test(finalBtn.href||'')) return {action: 'found_bot', link: finalBtn.href};
    finalBtn.click();
    return {action: 'clicked_final', href: finalBtn.href};
  }

  // Step button (pDone)
  const pDone = document.getElementById('pDone');
  if (pDone && !pDone.classList.contains('x')) {
    const btn = pDone.querySelector('button, a, input[type=submit]');
    if (btn) { btn.click(); return {action: 'clicked_pDone', text: btn.innerText||btn.value}; }
  }

  // Continue button (cont)
  const cont = document.getElementById('cont') || document.querySelector('.continue_btn, .start_btn, #rtg-snp21 button');
  if (cont && !cont.classList.contains('x')) {
    cont.click();
    return {action: 'clicked_cont'};
  }

  // Go button (go)
  const go = document.getElementById('go');
  if (go && !go.classList.contains('x') && go.offsetWidth > 0) {
    go.click();
    return {action: 'clicked_go'};
  }

  return {action: 'waiting', url: location.href};
}
"""

async def test_speed(pw, interval_ms, label):
    print(f"\n=======================================================")
    print(f"▶ TESTING TARGET SPEED: {label} ({interval_ms}ms per tick)")
    print(f"=======================================================")
    start = time.time()
    found_tg = None

    browser = await pw.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
    ctx = await browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 720})
    await ctx.add_init_script(get_init_script(interval_ms))
    page = await ctx.new_page()

    def hit(url):
        nonlocal found_tg
        m = BOT_RE.search(url)
        if m and not found_tg:
            found_tg = m.group(0)

    page.on("request", lambda r: hit(r.url))
    page.on("response", lambda r: hit(r.url))

    try:
        await page.goto(TEST_URL, wait_until="commit")

        for loop in range(90):  # max 45s
            await asyncio.sleep(0.5)
            if found_tg:
                break
            
            cur_url = page.url
            try:
                html = await page.content()
                if "This link has expired" in html:
                    print(f"  ❌ SERVER REJECTED (Link expired) at {time.time()-start:.1f}s on {cur_url[:50]}")
                    break

                m = BOT_RE.search(html) or BOT_RE.search(cur_url)
                if m:
                    found_tg = m.group(0)
                    break

                res = await page.evaluate(STEP_JS)
                act = res.get("action") if isinstance(res, dict) else ""
                print(f"[{loop+1}] {time.time()-start:.1f}s | url={cur_url[:45]} | action={act}", flush=True)
                if isinstance(res, dict) and res.get("link"):
                    found_tg = res["link"]
                    break
            except Exception as e:
                print(f"[{loop+1}] {time.time()-start:.1f}s | (navigating: {type(e).__name__})", flush=True)
    finally:
        await browser.close()

    elapsed = time.time() - start
    if found_tg:
        print(f"  🏆 SUCCESS in {elapsed:.1f}s! Bot Link: {found_tg}")
        return True, elapsed, found_tg
    else:
        print(f"  ❌ FAILED in {elapsed:.1f}s")
        return False, elapsed, None

async def main():
    async with async_playwright() as pw:
        # Test 1: 300ms per tick (~4.5s countdown per step -> ~20-25s total!)
        ok, el, tg = await test_speed(pw, 300, "FAST ~22s TARGET")
        if not ok:
            # Test 2: 450ms per tick (~6.5s countdown per step -> ~28-32s total!)
            ok, el, tg = await test_speed(pw, 450, "SAFE ~28s TARGET")

if __name__ == "__main__":
    asyncio.run(main())
