"""
Analyze network trace from full_trace_resolver.py.
"""
import json

with open("c:/Users/tsapa/Desktop/CODEX/telegramnewlink/network_trace.json", "r", encoding="utf-8") as f:
    events = json.load(f)

print(f"Total events: {len(events)}")
reqs = [e for e in events if e.get("type") == "REQUEST"]
resps = [e for e in events if e.get("type") == "RESPONSE"]

print("\n--- ALL UNIQUE REQUEST URLS ---")
seen = set()
for r in reqs:
    url = r["url"].split("?")[0]
    if url not in seen and not any(ad in url for ad in ["doubleclick", "googlesyndication", "google-analytics", "recaptcha", "adtrafficquality"]):
        seen.add(url)
        print(f"{r['method']} {r['url']}")
        if r.get("post_data"):
            print(f"   POST DATA: {r['post_data']}")

print("\n--- ALL REDIRECTS & IMPORTANT RESPONSES ---")
for resp in resps:
    if resp.get("location"):
        print(f"[{resp['status']}] {resp['url']} -> LOCATION: {resp['location']}")
    if resp.get("body_preview") and any(k in resp["url"] for k in [".php", "api", "short", "get"]):
        print(f"\nBODY from {resp['url']}:\n{resp['body_preview']}\n")
