# debug_resolve.py
import asyncio, time, os, sys, re
from urllib.parse import urljoin
import aiohttp
from aiohttp import ClientTimeout
from playwright.async_api import async_playwright

# Read SHORTLINKS env var: comma, newline or space separated list
SHORTLINKS_RAW = os.environ.get("SHORTLINKS") or os.environ.get("SHORTLINK") or "https://urlshortx.io/k4UBWjE"
# normalize into list
SHORTLINKS = [s.strip() for s in re.split(r"[\n,;\s]+", SHORTLINKS_RAW) if s.strip()]
HINDISINK_REFERER = "https://hindisink.com/best-free-ai-tools-content-design-or-productivity/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

async def try_http(shortlink):
    print(f"\n>>> HTTP redirect-following start: {shortlink}", flush=True)
    headers = {"User-Agent": USER_AGENT, "Referer": HINDISINK_REFERER}
    cur = shortlink
    async with aiohttp.ClientSession(timeout=ClientTimeout(total=15), headers=headers) as s:
        for hop in range(1, 12):
            try:
                print(f"  -> GET hop={hop}: {cur}", flush=True)
                async with s.get(cur, allow_redirects=False, ssl=False, timeout=ClientTimeout(total=10)) as r:
                    print(f"     status={r.status}", flush=True)
                    loc = r.headers.get("Location")
                    if loc:
                        loc_abs = loc if loc.startswith("http") else urljoin(cur, loc)
                        print(f"     Location: {loc_abs}", flush=True)
                        cur = loc_abs
                        txt = await r.text(errors="ignore")
                        if "t.me/" in txt or "telegram.me/" in txt:
                            print("     Found t.me in body of hop response", flush=True)
                            return {"found_in": "body", "snippet": txt[:2000]}
                        continue
                    body = await r.text(errors="ignore")
                    print("     Body snippet (first 2000 chars):", flush=True)
                    print((body or "")[:2000], flush=True)
                    return {"found_in": "body", "snippet": (body or "")[:2000]}
            except asyncio.TimeoutError:
                print("     Timeout on HTTP hop", flush=True)
                return None
            except Exception as e:
                print("     HTTP error:", type(e).__name__, e, flush=True)
                return None
    return None

FAST_CLICK_JS = r"""
() => {
  const sel = 'a.get-link, #getlink, a#final, #rtg-snp21 a, .start_btn, .continue_btn, #go, #cont, #pDone a, .btn-primary, .get-link';
  const el = document.querySelector(sel);
  if (el) {
    try { el.click(); } catch(e) {}
    return {clicked: sel, href: el.href || null};
  }
  // try text detection
  const bodyText = document.body ? document.body.innerText : "";
  const m = bodyText.match(/https?:\/\/(?:t\.me|telegram\.me)\/[A-Za-z0-9_]+\?start=[A-Za-z0-9_%+\/=\-]+/i);
  if (m) return {found_text: m[0]};
  return {found: false};
}
"""

def safe_name_for(url):
    s = re.sub(r'[^A-Za-z0-9]', '_', url)
    return s[:200]

async def try_playwright(shortlink, index):
    print(f"\n>>> Playwright fallback start: {shortlink}", flush=True)
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True, args=[
                "--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"
            ])
            print("  -> Browser launched OK", flush=True)
        except Exception as e:
            print("  ✖ Browser launch failed:", type(e).__name__, e, flush=True)
            return {"error": f"{type(e).__name__}: {e}"}
        context = await browser.new_context(user_agent=USER_AGENT, viewport={"width":1280,"height":720})
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        page = await context.new_page()
        seen = []
        page.on("request", lambda req: seen.append(("REQ", req.url)))
        page.on("response", lambda resp: seen.append(("RES", resp.url)))
        try:
            print("  -> goto", shortlink, flush=True)
            await page.goto(shortlink, referer=HINDISINK_REFERER, timeout=30000, wait_until="domcontentloaded")
        except Exception as e:
            print("  -> goto exception:", type(e).__name__, e, flush=True)
        for i in range(8):
            try:
                r = await page.evaluate(FAST_CLICK_JS)
                print("  -> evaluate result:", r, flush=True)
            except Exception as e:
                print("  -> evaluate error:", type(e).__name__, e, flush=True)
            await asyncio.sleep(1.5)
        try:
            url_now = page.url
            content = await page.content()
            # Save artifacts per link
            base = safe_name_for(shortlink)
            fname = f"debug_page_content_{index}_{base}.html"
            with open(fname, "w", encoding="utf-8") as fh:
                fh.write(content)
            try:
                shot = f"debug_page_screenshot_{index}_{base}.png"
                await page.screenshot(path=shot, full_page=True)
                print(f"  -> saved screenshot {shot}", flush=True)
            except Exception as e:
                print("  -> screenshot failed:", e, flush=True)
            print("  -> final page.url:", url_now, flush=True)
            print("  -> page content snippet (first 2000 chars):", flush=True)
            print((content or "")[:2000], flush=True)
        except Exception as e:
            print("  -> content read failed:", type(e).__name__, e, flush=True)
        print("  -> recorded requests/responses (last 50):", flush=True)
        for t,u in seen[-50:]:
            print(f"     {t} {u}", flush=True)
        await browser.close()
        return {"page_url": page.url, "seen": seen}
    return {}

async def main():
    print("Starting multi-link debug resolver", flush=True)
    if not SHORTLINKS:
        print("No links provided. Set SHORTLINKS env var.", flush=True)
        return

    for idx, sl in enumerate(SHORTLINKS, 1):
        print("\n" + "="*80)
        print(f"Resolving [{idx}/{len(SHORTLINKS)}]: {sl}", flush=True)
        http_res = await try_http(sl)
        if http_res and ("t.me" in (http_res.get("snippet","") or "") or "telegram.me" in (http_res.get("snippet","") or "")):
            print(f"HTTP found t.me content or redirect for {sl}.", flush=True)
            continue
        pw_res = await try_playwright(sl, idx)
        # small gap between tests
        await asyncio.sleep(1)
    print("\nAll links processed. Artifacts saved where available.", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
