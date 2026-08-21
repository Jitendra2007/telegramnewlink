"""
Diagnose Step 2 on Hindisink.
"""
import asyncio, sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

BOT_RE = re.compile(r'https?://(?:t\.me|telegram\.me)/([A-Za-z0-9_]+)\?start=([A-Za-z0-9_%+/=\-]+)', re.IGNORECASE)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

FAST_STEP_CLICKER = r"""
() => {
  const BOT = /(?:https?:\/\/)?(?:telegram\.me|t\.me)\/[A-Za-z0-9_]+\?start=[A-Za-z0-9_%+\/=\-]+/i;
  for (const a of document.querySelectorAll("a")) {
    if (BOT.test(a.href||"")) return {action:"found_bot", link:a.href};
  }
  const bt = (document.body||{}).innerText||"";
  const tm = bt.match(BOT);
  if (tm) return {action:"found_bot", link:tm[0]};

  // Remove ad gate immediately if present
  const gate = document.getElementById('hsg');
  if (gate) {
    gate.hidden = true;
    if (gate.parentNode) gate.parentNode.removeChild(gate);
    document.documentElement.style.overflow = '';
  }

  // 1. If Go to step X / Open link button is visible in pDone, click it!
  const pDone = document.getElementById('pDone');
  if (pDone && !pDone.classList.contains('x')) {
    const a = pDone.querySelector('a[href]');
    if (a) {
      if (BOT.test(a.href)) return {action:"found_bot", link:a.href};
      a.click();
      return {action:"clicked_step_next", text:a.innerText, href:a.href};
    }
    const btn = pDone.querySelector('button, input[type=submit]');
    if (btn) {
      btn.click();
      return {action:"clicked_step_next_btn", text:btn.innerText||btn.value};
    }
  }

  // 2. If Continue button is visible in pCont, click it!
  const pCont = document.getElementById('pCont');
  const cont = document.getElementById('cont');
  if (pCont && !pCont.classList.contains('x') && cont) {
    cont.click();
    return {action:"clicked_cont"};
  }

  // 3. Force speedup of hold timer (5s) if active
  const pHold = document.getElementById('pHold');
  if (pHold && !pHold.classList.contains('x')) {
    pHold.classList.add('x');
    if (pDone) pDone.classList.remove('x');
    return {action:"forced_hold_done"};
  }

  // 4. Force speedup of countdown timer if active
  const cd = document.getElementById('cd');
  if (cd && !cd.classList.contains('x')) {
    const num = document.getElementById('num');
    const bar = document.getElementById('bar');
    if (num) num.textContent = '0';
    if (bar) bar.style.width = '100%';
    if (pCont) pCont.classList.remove('x');
    cd.classList.add('x');
    return {action:"forced_countdown_done"};
  }

  // 5. If "Click here to verify" exists, click it (even if hidden by .x or styled)
  const go = document.getElementById('go');
  if (go && !go.classList.contains('x')) {
    go.click();
    return {action:"clicked_go"};
  }

  // If none matched, dump state
  return {
    action: "waiting",
    url: location.href,
    go: !!go,
    go_classes: go ? go.className : '',
    cd_classes: cd ? cd.className : '',
    pCont_classes: pCont ? pCont.className : '',
    pHold_classes: pHold ? pHold.className : '',
    pDone_classes: pDone ? pDone.className : '',
    hsg: !!document.getElementById('hsg')
  };
}
"""

async def main():
    start = time.time()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        ctx = await browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 720})
        
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
                print(f"  🔥 INTERCEPTED BOT LINK: {found_tg}")

        page.on("request", lambda r: hit(r.url))
        page.on("response", lambda r: hit(r.url))

        print("Navigating to https://UrlShortx.io/ypvGlC76 ...")
        await page.goto("https://UrlShortx.io/ypvGlC76", wait_until="commit", timeout=20000)

        for step in range(40):
            await asyncio.sleep(0.8)
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

                res = await page.evaluate(FAST_STEP_CLICKER)
                act = res.get("action") if isinstance(res, dict) else ""
                print(f"[{step+1}] {time.time()-start:.1f}s | url={cur[:50]} | action={act} | {res}")
                if isinstance(res, dict) and res.get("link"):
                    found_tg = res["link"]
                    break
            except Exception as e:
                print(f"[{step+1}] {time.time()-start:.1f}s | (busy/navigating: {type(e).__name__})")

        print(f"\n==========================================")
        elapsed = time.time() - start
        print(f"FINAL RESULT: {found_tg} in {elapsed:.1f}s")
        print(f"==========================================")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
