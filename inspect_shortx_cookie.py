"""
Inspect exact transition from Step 4 back to UrlShortx.
"""
import json

with open("c:/Users/tsapa/Desktop/CODEX/telegramnewlink/network_trace.json", "r", encoding="utf-8") as f:
    events = json.load(f)

for e in events:
    url = e.get("url", "")
    if "urlshortx.io" in url or "linkshortx.in" in url:
        print(f"[{e.get('type')}] {e.get('method', e.get('status'))} {url}")
        if e.get("post_data"):
            print(f"  POST: {e['post_data']}")
        if e.get("headers", {}).get("cookie"):
            print(f"  COOKIE: {e['headers']['cookie']}")
        if e.get("headers", {}).get("set-cookie"):
            print(f"  SET-COOKIE: {e['headers']['set-cookie']}")
