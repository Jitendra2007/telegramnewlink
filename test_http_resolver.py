"""
Test v6: Test with stealth flags + headless=False locally to confirm exact working resolver flow.
"""
import asyncio, sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
from urllib.parse import urlparse
from playwright.async_api import async_playwright

BOT_RE = re.compile(r'https?://(?:t\.me|telegram\.me)/([A-Za-z0-9_]+)\?start=([A-Za-z0-9_%+/=\-]+)', re.IGNORECASE)
FLOW_HOSTS = {"hindisink.com", "linkshortx.in", "urlshortx.io", "telegram.me"}
HINDISINK_REFERER = "https://hindisink.com/best-free-ai-tools-content-design-or-productivity/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

def host_of(url):
    try: return (urlparse(url).netloc or "").lower()
    except: return ""

INIT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(document, 'visibilityState', {get: () => 'visible', configurable: true});
    Object.defineProperty(document, 'hidden', {get: () => false, configurable: true});
    try { document.cookie = 'hsg=done:' + Date.now() + ';path=/;max-age=180;SameSite=Lax'; } catch(e) {}
    try { sessionStorage.setItem('hsg', 'done:' + Date.now()); } catch(e) {}
    const _origSI = window.setInterval;
    window.setInterval = function(fn, d, ...a) { return _origSI.call(window, fn, (d>500)?10:d, ...a); };
"""

FAST_STEP_JS = r"""
async () => {
  const BOT = /(?:https?:\/\/)?(?:telegram\.me|t\.me)\/[A-Za-z0-9_]+\?start=[A-Za-z0-9_%+\/=\-]+/i;
  for (const a of document.querySelectorAll("a")) {
    if (BOT.test(a.href||"")) return {action:"found_anchor", telegram:a.href};
  }
  const bt = (document.body||{}).innerText||"";
  const tm = bt.match(BOT);
  if (tm) return {action:"found_text", telegram:tm[0]};

  const t = (document.title||"").toLowerCase();
  if (t.includes("checking your browser") || t.includes("just a moment") ||
      document.querySelector("#challenge-running, #cf-challenge-running"))
    return {action:"waiting_cloudflare"};

  const now = Date.now();
  try { document.cookie='hsg=done:'+now+';path=/;max-age=180;SameSite=Lax'; } catch(e) {}
  try { sessionStorage.setItem('hsg','done:'+now); } catch(e) {}
  const gate = document.getElementById('hsg');
  if (gate) { gate.hidden=true; if(gate.parentNode)gate.parentNode.removeChild(gate); document.documentElement.style.overflow=''; }

  const go = document.getElementById('go');
  if (go) {
    go.click();
    const n=document.getElementById('num'),b=document.getElementById('bar');
    if(n)n.textContent='0';if(b)b.style.width='100%';
    const pc=document.getElementById('pCont'),cd=document.getElementById('cd');
    if(pc)pc.classList.remove('x');if(cd)cd.classList.add('x');
    for(let i=1;i<9999;i++){try{clearInterval(i);}catch(e){}}
    return {action:"bypassed_go"};
  }
  const cont = document.getElementById('cont');
  if (cont && !cont.closest('.x')) {
    cont.click();
    const ph=document.getElementById('pHold'),pd=document.getElementById('pDone');
    if(ph)ph.classList.add('x');if(pd)pd.classList.remove('x');
    for(let i=1;i<9999;i++){try{clearInterval(i);}catch(e){}}
    return {action:"bypassed_cont"};
  }
  const pd = document.getElementById('pDone');
  if (pd && !pd.classList.contains('x')) {
    const a=pd.querySelector('a[href]');
    if(a){if(BOT.test(a.href))return{action:"found_pDone",telegram:a.href};a.click();return{action:"clicked_pDone",href:a.href};}
    const btn=pd.querySelector('button');if(btn){btn.click();return{action:"clicked_pDone_btn"};}
  }

  const gl = document.querySelector(".get-link");
  if (gl) {
    const dis = gl.classList.contains("disabled") ||
                gl.getAttribute("aria-disabled")==="true" ||
                window.getComputedStyle(gl).pointerEvents==="none";
    if (dis) return {action:"waiting_final_gate"};
    return {action:"click_get_link"};
  }

  const f = document.querySelector("form#fwd, form#rtg, form#landing");
  if(f){try{HTMLFormElement.prototype.submit.call(f);return{action:"submitted_form",id:f.id};}catch(e){}}
  const fb = document.getElementById("final")||document.querySelector("#rtg-snp21 a, .btn-primary, .btn-success, .continue_btn, .start_btn");
  if(fb){if(BOT.test(fb.href||''))return{action:"found_final",telegram:fb.href};fb.click();return{action:"clicked_final"};}

  return {action:"nothing_matched", url:location.href, title:document.title};
}
"""

def norm(url):
    m = BOT_RE.search(url) if url else None
    return f"https://t.me/{m.group(1)}?start={m.group(2)}" if m else None

async def resolve(pw, shortlink):
    start = time.time()
    found = None
    browser = None
    try:
        browser = await pw.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ]
        )
        ctx = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True
        )
        await ctx.add_init_script(INIT_SCRIPT)

        async def on_popup(pop):
            try:
                if not ctx.pages or pop == ctx.pages[0]: return
                for _ in range(15):
                    if (pop.url or "") != "about:blank": break
                    await asyncio.sleep(0.1)
                ph = host_of(pop.url)
                if not any(h in ph for h in ["linkshortx","urlshortx","hindisink","telegram"]):
                    print(f"    [AdBlock] closing spam: {pop.url[:60]}")
                    await pop.close()
                else:
                    print(f"    [Flow tab] keeping: {pop.url[:60]}")
            except: pass
        ctx.on("page", lambda p: asyncio.create_task(on_popup(p)))

        page = await ctx.new_page()
        def hit(url):
            nonlocal found
            if found: return
            m = BOT_RE.search(url)
            if m: found = m.group(0)
        page.on("request", lambda r: hit(r.url))
        page.on("response", lambda r: hit(r.url))

        def attach(p):
            p.on("request", lambda r: hit(r.url))
            p.on("response", lambda r: hit(r.url))
        ctx.on("page", attach)

        try: await page.set_extra_http_headers({"referer": HINDISINK_REFERER})
        except: pass

        try: await page.goto(shortlink, wait_until="commit", timeout=20000)
        except Exception as e: print(f"    nav: {type(e).__name__}: {e}")

        await asyncio.sleep(2.0)
        if found:
            print(f"    ✅ EARLY HIT {time.time()-start:.1f}s")
            await browser.close(); return norm(found)

        for cycle in range(50):
            if found: break
            elapsed = time.time()-start
            if elapsed > 45.0: break
            try:
                active = ctx.pages[0] if ctx.pages else page
                cur = active.url or ""
                html = await active.content()
                m = BOT_RE.search(html) or BOT_RE.search(cur)
                if m: found = m.group(0); break

                r = await active.evaluate(FAST_STEP_JS)
                action = r.get("action","") if isinstance(r,dict) else ""
                tg = r.get("telegram") if isinstance(r,dict) else None
                print(f"    [{cycle+1}] {elapsed:.1f}s action={action} url={cur[:60]}")
                if tg: found = tg; break

                if action == "click_get_link":
                    try:
                        await active.evaluate("""() => {
                            for (const el of document.querySelectorAll('[data-vignette-loaded="true"], ins[data-google-query-id]'))
                                try{el.remove();}catch(e){}
                            for (const el of document.querySelectorAll('iframe'))
                                if((el.src||'').includes('safeframe')||(el.src||'').includes('googlesyndication'))
                                    try{el.remove();}catch(e){}
                        }""")
                        await active.click(".get-link", timeout=5000, force=True)
                    except Exception as e:
                        print(f"    .get-link err: {type(e).__name__}: {e}")
                    await asyncio.sleep(1.5)
                elif action == "waiting_cloudflare":
                    await asyncio.sleep(1.5)
                elif action == "waiting_final_gate":
                    await asyncio.sleep(1.0)
                elif action.startswith("bypassed_") or action.startswith("clicked_") or action.startswith("submitted_"):
                    await asyncio.sleep(1.0)
                else:
                    await asyncio.sleep(0.5)
            except Exception as e:
                print(f"    [{cycle+1}] err: {type(e).__name__}: {e}")
                await asyncio.sleep(1.0)

    except Exception as e:
        print(f"    LAUNCH: {type(e).__name__}: {e}")
    finally:
        if browser:
            try: await browser.close()
            except: pass

    elapsed = time.time()-start
    if found:
        result = norm(found)
        print(f"    ✅ RESOLVED in {elapsed:.1f}s: {result}")
        return result
    print(f"    ⚠️ UNRESOLVED after {elapsed:.1f}s")
    return None

async def main():
    print("="*65)
    print("  TEST v6: Non-headless Playwright (same as local working resolver)")
    print("="*65)
    async with async_playwright() as pw:
        for link in ["https://UrlShortx.io/ypvGlC76", "https://linkshortx.in/KteI"]:
            print(f"\n🔗 {link}")
            result = await resolve(pw, link)
            if result: print(f"  => ✅ {result}")
            else: print(f"  => ❌ unresolved")
    print("\n"+"="*65)

if __name__ == "__main__":
    asyncio.run(main())
