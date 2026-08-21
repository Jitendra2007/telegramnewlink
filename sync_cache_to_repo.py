"""
Sync all resolved links into master_resolved_cache.json with utf-8 encoding.
"""
import json, re, os, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

SQL_MASTER = Path(r"C:\Users\tsapa\Desktop\CODEX\pure_audioverse_219_stories_master.sql")
RESOLVED_TXT = Path(r"C:\Users\tsapa\Desktop\CODEX\newly_resolved_links.txt")
CACHE_FILE = Path(r"c:\Users\tsapa\Desktop\CODEX\telegramnewlink\master_resolved_cache.json")

cache = {}
if CACHE_FILE.exists():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {}

print(f"Initial cache entries: {len(cache):,}")

# 1. From newly_resolved_links.txt
if RESOLVED_TXT.exists():
    with open(RESOLVED_TXT, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "->" in line:
                parts = line.strip().split("->")
                if len(parts) == 2:
                    s_url = parts[0].strip()
                    b_url = parts[1].strip()
                    if s_url and b_url and ("t.me" in b_url or "telegram.me" in b_url):
                        cache[s_url] = b_url

# 2. From pure_audioverse_219_stories_master.sql
if SQL_MASTER.exists():
    with open(SQL_MASTER, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "RESOLVED" in line:
                m_short = re.search(r"'(https?://(?:urlshortx\.io|linkshortx\.in)/[^']+)'", line)
                m_bot = re.search(r"'(https?://(?:t\.me|telegram\.me)/[^']+)'", line)
                if m_short and m_bot:
                    cache[m_short.group(1)] = m_bot.group(1)

print(f"Total synced cache entries: {len(cache):,}")

with open(CACHE_FILE, "w", encoding="utf-8") as f:
    json.dump(cache, f, indent=2, ensure_ascii=False)

print(f"Saved updated master_resolved_cache.json successfully!")
