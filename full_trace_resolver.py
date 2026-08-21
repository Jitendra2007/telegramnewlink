"""
Full Network & DOM Tracer for Shortlinks.
Records every HTTP request, response, cookie, redirect, and DOM mutation.
"""
import asyncio, sys, re, json, time
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

BOT_RE = re.compile(r'https?://(?:t\.me|telegram\.me)/([A-Za-z0-9_]+)\?start=([A-Za-z0-9_%+/=\-]+)', re.IGNORECASE)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

TEST_URL = "https://UrlShortx.io/ypvGlC76"

async def main():
    print(f"=== FULL NETWORK & TRACE INVESTIGATION FOR {TEST_URL} ===")
    events = []
    
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        ctx = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True
        )
        
        page = await ctx.new_page()

        async def log_request(req):
            post_data = req.post_data
            headers = await req.all_headers()
            events.append({
                "time": time.time(),
                "type": "REQUEST",
                "method": req.method,
                "url": req.url,
                "post_data": post_data,
                "headers": {k: v for k, v in headers.items() if k.lower() in ["cookie", "referer", "user-agent", "content-type", "x-requested-with"]}
            })
            m = BOT_RE.search(req.url)
            if m:
                print(f"\n🔥🔥🔥 [BOT LINK FOUND IN REQUEST] {m.group(0)}\n")

        async def log_response(resp):
            status = resp.status
            url = resp.url
            headers = await resp.all_headers()
            location = headers.get("location", "")
            
            # Check if this is an API or redirect or contains bot link
            body_preview = ""
            if any(ext in url for ext in [".php", "/api", "short", "get-link", "ajax", "token", "verify"]) or "application/json" in headers.get("content-type", ""):
                try:
                    text = await resp.text()
                    body_preview = text[:500]
                    m = BOT_RE.search(text)
                    if m:
                        print(f"\n🔥🔥🔥 [BOT LINK FOUND IN RESPONSE BODY of {url}]: {m.group(0)}\n")
                except:
                    pass

            events.append({
                "time": time.time(),
                "type": "RESPONSE",
                "status": status,
                "url": url,
                "location": location,
                "headers": {k: v for k, v in headers.items() if k.lower() in ["set-cookie", "location", "content-type"]},
                "body_preview": body_preview
            })
            m = BOT_RE.search(url) or BOT_RE.search(location)
            if m:
                print(f"\n🔥🔥🔥 [BOT LINK FOUND IN RESPONSE URL/LOCATION] {m.group(0)}\n")

        page.on("request", log_request)
        page.on("response", log_response)

        print(f"Navigating to {TEST_URL}...")
        await page.goto(TEST_URL, wait_until="commit", timeout=25000)

        # Let the page run naturally for 40 seconds so we record the exact natural flow
        for sec in range(40):
            await asyncio.sleep(1)
            cur_url = page.url
            print(f"[{sec+1}s] Current page URL: {cur_url}")
            
            # Extract any forms or buttons on page
            try:
                state = await page.evaluate("""() => {
                    const forms = Array.from(document.forms).map(f => ({id: f.id, action: f.action, method: f.method}));
                    const cookies = document.cookie;
                    const session = Object.entries(sessionStorage);
                    const local = Object.entries(localStorage);
                    const title = document.title;
                    const hsg = !!document.getElementById('hsg');
                    const go = !!document.getElementById('go');
                    const getLink = !!document.querySelector('.get-link');
                    return {title, cookies, session, local, forms, hsg, go, getLink};
                }""")
                print(f"     Title: {state.get('title')} | forms: {len(state.get('forms',[]))} | hsg: {state.get('hsg')} | go: {state.get('go')} | getLink: {state.get('getLink')}")
                print(f"     Cookies: {state.get('cookies')[:150]}")
            except Exception as e:
                print(f"     (eval busy: {type(e).__name__})")

        # Save all logged events to JSON file for analysis
        with open("network_trace.json", "w", encoding="utf-8") as f:
            json.dump(events, f, indent=2, ensure_ascii=False)

        print("\nSaved network_trace.json successfully.")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
