"""
Fast Optimized Resolver with precise minimum wait timing (10s) and parallel workers.
"""
import asyncio, sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

BOT_RE = re.compile(r'https?://(?:t\.me|telegram\.me)/([A-Za-z0-9_]+)\?start=([A-Za-z0-9_%+/=\-]+)', re.IGNORECASE)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

STEP_HELPER_JS = r"""
() => {
  const BOT = /(?:https?:\/\/)?(?:telegram\.me|t\.me)\/[A-Za-z0-9_]+\?start=[A-Za-z0-9_%+\/=\-]+/i;
  for (const a of document.querySelectorAll('a')) {
    if (BOT.test(a.href||'')) return {action: 'found_bot', link: a.href};
  }
  const bt = (document.body||{}).innerText||'';
  const tm = bt.match(BOT);
  if (tm) return {action: 'found_bot', link: tm[0]};

  // Remove ad gate overlay if present
  const gate = document.getElementById('hsg');
  if (gate) {
    gate.hidden = true;
    if (gate.parentNode) gate.parentNode.removeChild(gate);
    document.documentElement.style.overflow = '';
  }

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

  // 5. Check timers
  const cd = document.getElementById('cd');
  if (cd && !cd.classList.contains('x')) {
    const num = (document.getElementById('num') || {}).innerText || '';
    return {action: 'timer_countdown', left: num};
  }
  const pHold = document.getElementById('pHold');
  if (pHold && !pHold.classList.contains('x')) {
    return {action: 'timer_hold'};
  }

  return {action: 'waiting', url: location.href};
}
"""

async def resolve_single_link(ctx, shortlink):
    start = time.time()
    found_tg = None
    page = await ctx.new_page()

    def hit(url):
        nonlocal found_tg
        m = BOT_RE.search(url)
        if m and not found_tg:
            found_tg = m.group(0)

    page.on("request", lambda r: hit(r.url))
    page.on("response", lambda r: hit(r.url))

    try:
        print(f"🚀 [START]: {shortlink}")
        await page.goto(shortlink, wait_until="commit", timeout=25000)

        for _ in range(110):  # max ~90-100s
            if found_tg:
                break
            await asyncio.sleep(0.8)

            try:
                html = await page.content()
                m = BOT_RE.search(html) or BOT_RE.search(page.url or "")
                if m:
                    found_tg = m.group(0)
                    break

                res = await page.evaluate(STEP_HELPER_JS)
                if isinstance(res, dict) and res.get("link"):
                    found_tg = res["link"]
                    break
            except Exception:
                pass
    except Exception as e:
        print(f"  ⚠️ Error for {shortlink}: {e}")
    finally:
        await page.close()

    elapsed = time.time() - start
    if found_tg:
        print(f"  ✅ [RESOLVED in {elapsed:.1f}s]: {shortlink} -> {found_tg}")
        return found_tg
    else:
        print(f"  ❌ [FAILED in {elapsed:.1f}s]: {shortlink}")
        return None

async def main():
    test_links = [
        "https://UrlShortx.io/ypvGlC76",
        "https://linkshortx.in/KteI",
        "https://linkshortx.in/C6S1hn13"
    ]
    print(f"=== TESTING FAST PARALLEL RESOLVER FOR {len(test_links)} LINKS ===")
    total_start = time.time()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        ctx = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 720}
        )
        await ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            try { document.cookie = 'hsg=done:' + Date.now() + ';path=/;max-age=180;SameSite=Lax'; } catch(e) {}
            try { sessionStorage.setItem('hsg', 'done:' + Date.now()); } catch(e) {}
        """)

        # Run links concurrently!
        tasks = [resolve_single_link(ctx, link) for link in test_links]
        results = await asyncio.gather(*tasks)

        total_elapsed = time.time() - total_start
        print(f"\n=======================================================")
        print(f"PARALLEL RESOLUTION COMPLETED IN {total_elapsed:.1f}s TOTAL")
        for link, res in zip(test_links, results):
            print(f"  {link} -> {res}")
        print(f"=======================================================")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
