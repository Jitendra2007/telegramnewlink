import json
from pathlib import Path

CACHE_FILE = Path(r"c:\Users\tsapa\Desktop\CODEX\telegramnewlink\master_resolved_cache.json")

NEW_PAIRS = {
    "https://urlshortx.io/88dIotn": "https://telegram.me/AVFile_BOT?start=Z2V0LTQ2MTQ3NDAyNzY3MDY4MzgzLTQ2MTU2NDMzMzczNTk4MDAw",
    "https://linkshortx.in/FKBm": "https://telegram.me/AVFile_BOT?start=Z2V0LTQ2MTY3NDcwNzgxNTc4NjQzLTQ2MTc2NTAxMzg4MTA4MjYw",
    "https://urlshortx.io/1sQKRr": "https://telegram.me/AVFile_BOT?start=Z2V0LTQ2MTc3NTA0Nzg4ODMzNzczLTQ2MTg2NTM1Mzk1MzYzMzkw",
    "https://linkshortx.in/te578uY": "https://telegram.me/AVFile_BOT?start=Z2V0LTQ2MTg3NTM4Nzk2MDg4OTAzLTQ2MTk2NTY5NDAyNjE4NTIw"
}

if CACHE_FILE.exists():
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        cache = json.load(f)
else:
    cache = {}

updated = 0
for k, v in NEW_PAIRS.items():
    if k not in cache:
        cache[k] = v
        updated += 1

with open(CACHE_FILE, "w", encoding="utf-8") as f:
    json.dump(cache, f, indent=2, ensure_ascii=False)

print(f"Added {updated} pairs. Total in cache: {len(cache):,}")
