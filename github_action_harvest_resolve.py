#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CODEX GitHub Actions Automated Story Harvester & Shortlink Resolver Engine
Runs on Microsoft Azure runners with 7 GB RAM.
Auto-scans all Telegram channels across dual accounts, resolves new links, and persists to SQL/JSON.
"""

import asyncio
import datetime
import json
import os
import re
import sqlite3
import sys
import time
from urllib.parse import urlparse
from aiohttp import ClientSession, ClientTimeout
from telethon import TelegramClient
from telethon.sessions import StringSession
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding='utf-8')

# Environment variables from GitHub Action Secrets
API_ID = int(os.environ.get("API_ID", "36198115"))
API_HASH = os.environ.get("API_HASH", "ce040e05f933e3e0a811f186c3d5d3bb")
SESSION_STR_MAIN = os.environ.get("TELEGRAM_STRING_SESSION", "")
SESSION_STR_SUB = os.environ.get("TELEGRAM_STRING_SESSION_SUB", "")

CACHE_PATH = "master_resolved_cache.json"
SKIPPED_CHANNELS_PATH = "skipped_channels_no_shortlinks.json"
RESOLVED_OUTPUT_SQL_PATH = "resolved_output_master.sql"
DB_PATH = "live_harvest.db"
STORY_SETS_DIR = "story_sets"

HINDISINK_REFERER = "https://hindisink.com/best-free-ai-tools-content-design-or-productivity/"
BOT_RE = re.compile(r'https?://(?:t\.me|telegram\.me)/([A-Za-z0-9_]+)\?start=([A-Za-z0-9_%+/=\-]+)', re.IGNORECASE)
SHORTLINK_RE = re.compile(r'https?://(?:linkshortx\.in|urlshortx\.io|hindisink\.com|v2links\.[a-z]+|droplink\.[a-z]+)/[A-Za-z0-9_\-]+', re.IGNORECASE)

ABBREV_MAP = {
    'jr': "Jack's Retribution (English) •|Pocket FM|•",
    'sn': "Saving Nora (English) •|Pocket FM|•",
    'flbm': "First Legendary Beast Master(English) •|Pocket FM|•",
    'tdmb': "The Duke's Masked Bride (English) •|Pocket FM|•",
    'bth': "Battle through the Heavens (English) •|Pocket FM|•",
    'lom': "Lord of Money (English) •|Pocket FM|•",
    'spm': "Supreme Magus (English) •|Pocket FM|•",
    's&b': "Shadow and Bone (English) •|Pocket FM|•",
    'syl': "Sylvia (English) •|Pocket FM|•",
}

MASTER_RESOLVED_CACHE = {}
SKIPPED_CHANNELS_REGISTRY = {}


def load_data():
    global MASTER_RESOLVED_CACHE, SKIPPED_CHANNELS_REGISTRY
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                MASTER_RESOLVED_CACHE = json.load(f)
            print(f"📦 Loaded {len(MASTER_RESOLVED_CACHE):,} pre-resolved link mappings from master cache.", flush=True)
        except Exception as e:
            print(f"⚠️ Could not load cache: {e}", flush=True)

    if os.path.exists(SKIPPED_CHANNELS_PATH):
        try:
            with open(SKIPPED_CHANNELS_PATH, "r", encoding="utf-8") as f:
                SKIPPED_CHANNELS_REGISTRY = json.load(f)
            print(f"🚫 Loaded {len(SKIPPED_CHANNELS_REGISTRY):,} channels in skip registry (0 shortlinks).", flush=True)
        except Exception as e:
            print(f"⚠️ Could not load skipped channels: {e}", flush=True)


def save_skipped_channel(cid, cname, reason="no_shortlinks"):
    SKIPPED_CHANNELS_REGISTRY[cid] = {
        "channel_name": cname,
        "reason": reason,
        "skipped_at": datetime.datetime.now().isoformat()
    }
    try:
        with open(SKIPPED_CHANNELS_PATH, "w", encoding="utf-8") as f:
            json.dump(SKIPPED_CHANNELS_REGISTRY, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Failed to save skip list: {e}", flush=True)


def save_cache_to_disk():
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(MASTER_RESOLVED_CACHE, f, ensure_ascii=False, indent=2)
        print(f"💾 Updated {CACHE_PATH} with {len(MASTER_RESOLVED_CACHE):,} pairs.", flush=True)
    except Exception as e:
        print(f"⚠️ Failed to save cache: {e}", flush=True)


def append_resolved_to_sql_file(cid, cname, ordered_items):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(RESOLVED_OUTPUT_SQL_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n-- ═══════════════════════════════════════════════════════════════════\n")
            f.write(f"-- Channel: {cname} | ID: {cid} | Episodes: {len(ordered_items)} | Written: {now_str}\n")
            f.write(f"-- ═══════════════════════════════════════════════════════════════════\n")
            if ordered_items:
                f.write(f"INSERT INTO `pocket_fm_all_in_one_links` (`channel_id`, `channel_name`, `button_range`, `start_episode`, `end_episode`, `shortlink_url`, `telegram_bot_link`, `status`, `source`) VALUES\n")
                val_lines = []
                for item in ordered_items:
                    cname_esc = cname.replace("'", "''")
                    surl = (item.get('shortlink') or 'N/A').replace("'", "''")
                    burl = (item.get('bot_link') or 'N/A').replace("'", "''")
                    rng = item.get('range_label', '')
                    sep = item.get('start_ep', 0)
                    eep = item.get('end_ep', 0)
                    status = 'RESOLVED' if burl != 'N/A' else 'PENDING'
                    val_lines.append(f"('{cid}', '{cname_esc}', '{rng}', {sep}, {eep}, '{surl}', '{burl}', '{status}', 'github_action_auto')")
                f.write(",\n".join(val_lines) + ";\n")
        print(f"    💾 SQL appended: {len(ordered_items)} rows for '{cname}' -> {RESOLVED_OUTPUT_SQL_PATH}", flush=True)
    except Exception as e:
        print(f"    ⚠️ Failed to append SQL: {e}", flush=True)


def clean_story_title(cname):
    if not cname:
        return ""
    cname = cname.replace("\\'", "'").replace("''", "'").strip()
    cname = re.sub(r'_(?:unresolved_yet|fully_resolved|pending|resolved|unresolved|backup)(?:_\d{4}-\d{2}-\d{2})?', '', cname, flags=re.IGNORECASE)
    cname = re.sub(r'\b(?:fully\s*resolved|unresolved\s*yet|pending|backup)\b', '', cname, flags=re.IGNORECASE)
    cname = re.sub(r'\.txt$', '', cname, flags=re.IGNORECASE)
    cname = re.sub(r'\s*•_Pocket FM_•', ' •|Pocket FM|•', cname)
    cname = re.sub(r'\s*•_Pocket FM_', ' •|Pocket FM|•', cname)
    cname = re.sub(r'\s*•\s*Pocket FM\s*•', ' •|Pocket FM|•', cname)
    cname = re.sub(r'\s*\|\s*Pocket FM\s*\|', ' •|Pocket FM|•', cname)
    cname = re.sub(r'\s*•\|Pocket FM\|•', ' •|Pocket FM|•', cname)
    cname = cname.strip()
    
    if cname.lower() in ABBREV_MAP:
        cname = ABBREV_MAP[cname.lower()]
        
    low = cname.lower()
    noise_words = ['null', 'all in one', 'all_channels', 'human verified', 'remaining_pending', 'error:', 'failed', 'cannot send', '_data', 'data', 'links', 'pending_links', 'resolved_links', 'sample', 'back-up', 'backup']
    if any(low == nw or low.startswith(nw + ' ') or low.endswith(' ' + nw) for nw in noise_words) or low in noise_words:
        return ""
    if re.match(r'^-?\d+$', cname) or len(cname) < 3:
        return ""
    return cname


def parse_range_numbers(range_str):
    if not range_str:
        return None, None, None
    if re.search(r'\b202[4-6]-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b', range_str):
        return None, None, None
    m = re.search(r'(\d+)\s*[-–]\s*(\d+)', range_str)
    if m:
        s, e = int(m.group(1)), int(m.group(2))
        if 2024 <= s <= 2026 and e < 2200 and (e - s < 150):
            return None, None, None
        if e < s:
            if s >= 100 and e < 100:
                hundreds = (s // 100) * 100
                if hundreds + e >= s:
                    e = hundreds + e
                elif hundreds + 100 + e >= s:
                    e = hundreds + 100 + e
            elif s >= 1000 and e < 1000:
                thousands = (s // 1000) * 1000
                if thousands + e >= s:
                    e = thousands + e
        formatted = f"{s:02d}-{e:02d}" if s < 100 and e < 100 else f"{s}-{e}"
        return s, e, formatted
    return None, None, None


def normalize_bot_link(url):
    if not url or url == "N/A":
        return "N/A"
    m = BOT_RE.search(url)
    if m:
        bot_name = m.group(1)
        payload = m.group(2)
        return f"https://t.me/{bot_name}?start={payload}"
    return "N/A"


INVALID_SLUGS_RE = re.compile(
    r'^/(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\d+$'
    r'|^/\d{1,2}(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)$'
    r'|^/(?:promo|index|daily|update|updates|batch|channel|join|backup|sample|test|help|admin|rules|terms|all_in_one|free_episodes)$',
    re.IGNORECASE
)

def normalize_shortlink(url):
    if not url or url == "N/A":
        return "N/A"
    m = SHORTLINK_RE.search(url)
    if m:
        clean_url = m.group(0).strip()
        path = urlparse(clean_url).path
        if INVALID_SLUGS_RE.search(path):
            return "N/A"
        return clean_url
    return "N/A"


async def resolve_one_shortlink(playwright_instance, shortlink):
    if shortlink in MASTER_RESOLVED_CACHE:
        return MASTER_RESOLVED_CACHE[shortlink]

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": HINDISINK_REFERER,
    }

    # 1. HTTP Redirect Follower
    found = None
    current_url = shortlink
    try:
        async with ClientSession(timeout=ClientTimeout(total=10), headers=HEADERS) as session:
            for _ in range(10):
                if not current_url or not current_url.startswith("http"):
                    break
                m = BOT_RE.search(current_url)
                if m:
                    found = m.group(0)
                    break
                try:
                    async with session.get(current_url, allow_redirects=False, ssl=False, timeout=ClientTimeout(total=8)) as resp:
                        loc = resp.headers.get("Location", "")
                        if loc:
                            m = BOT_RE.search(loc)
                            if m:
                                found = m.group(0)
                                break
                            current_url = loc if loc.startswith("http") else __import__("urllib.parse", fromlist=["urljoin"]).urljoin(current_url, loc)
                            continue
                        body = await resp.text(encoding="utf-8", errors="ignore")
                        m = BOT_RE.search(body)
                        if m:
                            found = m.group(0)
                            break
                        break
                except Exception:
                    break
    except Exception:
        pass

    if found:
        result = normalize_bot_link(found)
        if result != "N/A":
            print(f"    ⚡ [HTTP OK]: {shortlink} -> {result}", flush=True)
            MASTER_RESOLVED_CACHE[shortlink] = result
            return result

    # 2. Playwright Chromium Browser Engine (7 GB RAM Azure Runner)
    print(f"    🌐 [PLAYWRIGHT BROWSER]: {shortlink}", flush=True)
    pw_found = None
    browser = None
    try:
        browser = await playwright_instance.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox", "--disable-setuid-sandbox",
                "--disable-dev-shm-usage", "--disable-gpu",
                "--disable-extensions", "--ignore-certificate-errors",
                "--disable-images", "--blink-settings=imagesEnabled=false",
            ]
        )
        context = await browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 720},
            java_script_enabled=True,
        )
        page = await context.new_page()

        def check_hit(url):
            nonlocal pw_found
            if pw_found: return
            m = BOT_RE.search(url)
            if m:
                pw_found = m.group(0)

        page.on("request", lambda req: check_hit(req.url))
        page.on("response", lambda resp: check_hit(resp.url))

        # Phase 1: Fast Direct Referer
        try:
            await page.goto(shortlink, referer=HINDISINK_REFERER, wait_until="domcontentloaded", timeout=14000)
            for _ in range(12):
                if pw_found: break
                res = await page.evaluate(r"""() => {
                    const gl = document.querySelector(".get-link, #getlink, a.get-link");
                    if (!gl) return {found: false};
                    const locked = gl.classList.contains("disabled") || (gl.innerText||'').includes("wait");
                    if (!locked) {
                        try { gl.click(); } catch(e){}
                        return {clicked: true};
                    }
                    return {locked: true};
                }""")
                if res.get("clicked"):
                    await asyncio.sleep(2.0)
                    break
                await asyncio.sleep(1.0)
        except Exception:
            pass

        # Phase 2: Sequential State Machine Fallback
        if not pw_found:
            try:
                await page.goto(shortlink, wait_until="commit", timeout=12000)
                for _ in range(25):
                    if pw_found: break
                    try:
                        await page.evaluate(r"""() => {
                            const b = document.querySelector('a#final, #rtg-snp21 a, .get-link, a.btn-primary');
                            if (b) { b.click(); return; }
                            const pDone = document.getElementById('pDone');
                            if (pDone && !pDone.classList.contains('x')) {
                                const btn = pDone.querySelector('button, a, input[type=submit]');
                                if (btn) { btn.click(); return; }
                            }
                            const cont = document.getElementById('cont') || document.querySelector('.continue_btn');
                            if (cont && !cont.classList.contains('x')) { cont.click(); return; }
                            const go = document.getElementById('go');
                            if (go && !go.classList.contains('x') && go.offsetWidth > 0) { go.click(); return; }
                        }""")
                    except Exception:
                        pass
                    await asyncio.sleep(1.0)
            except Exception:
                pass

        if not pw_found:
            try:
                c = await page.content()
                m = BOT_RE.search(c) or BOT_RE.search(page.url or "")
                if m:
                    pw_found = m.group(0)
            except Exception:
                pass

    except Exception as e:
        print(f"    ⚠️ Browser Error: {e}", flush=True)
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass

    if pw_found:
        res = normalize_bot_link(pw_found)
        if res != "N/A":
            print(f"    ✅ [RESOLVED OK]: {shortlink} -> {res}", flush=True)
            MASTER_RESOLVED_CACHE[shortlink] = res
            return res

    print(f"    ⚠️ [PENDING]: {shortlink}", flush=True)
    return None


async def run_batch_harvest_and_resolve():
    print("=" * 90, flush=True)
    print("🚀 CODEX GITHUB ACTIONS AUTO-HARVEST & RESOLVER ENGINE", flush=True)
    print(f"⏰ Execution Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}", flush=True)
    print("=" * 90, flush=True)

    load_data()
    os.makedirs(STORY_SETS_DIR, exist_ok=True)

    clients = []
    channel_targets = []
    seen_channel_ids = set()

    # 1. Connect Account 1 (Rock)
    if SESSION_STR_MAIN:
        client_main = TelegramClient(StringSession(SESSION_STR_MAIN), API_ID, API_HASH, timeout=20)
        await client_main.connect()
        if await client_main.is_user_authorized():
            me1 = await client_main.get_me()
            print(f"✅ Account 1 Connected: {me1.first_name} (+{me1.phone})", flush=True)
            clients.append(client_main)
            d1 = await client_main.get_dialogs()
            for d in d1:
                if d.is_channel:
                    clean_id = re.sub(r'^-?100', '', str(d.id)).lstrip('-')
                    cname = clean_story_title(d.title)
                    if cname and clean_id not in seen_channel_ids:
                        seen_channel_ids.add(clean_id)
                        channel_targets.append((client_main, d, clean_id, cname))

    # 2. Connect Account 2 (Syamala)
    if SESSION_STR_SUB:
        try:
            client_sub = TelegramClient(StringSession(SESSION_STR_SUB), API_ID, API_HASH, timeout=20)
            await client_sub.connect()
            if await client_sub.is_user_authorized():
                me2 = await client_sub.get_me()
                print(f"✅ Account 2 Connected: {me2.first_name} (+{me2.phone})", flush=True)
                clients.append(client_sub)
                d2 = await client_sub.get_dialogs()
                for d in d2:
                    if d.is_channel:
                        clean_id = re.sub(r'^-?100', '', str(d.id)).lstrip('-')
                        cname = clean_story_title(d.title)
                        if cname and clean_id not in seen_channel_ids:
                            seen_channel_ids.add(clean_id)
                            channel_targets.append((client_sub, d, clean_id, cname))
        except Exception as e:
            print(f"⚠️ Account 2 note: {e}", flush=True)

    if not clients:
        print("❌ No active Telegram accounts found! Check GitHub Action Secrets.", flush=True)
        return

    print(f"📡 Found {len(channel_targets)} total channels across both accounts.", flush=True)

    total_resolved_this_run = 0
    total_channels_processed = 0

    async with async_playwright() as p:
        for idx, (cli, d, cid, cname) in enumerate(channel_targets, 1):
            if cid in SKIPPED_CHANNELS_REGISTRY:
                continue

            raw_channel_items = []
            try:
                async for message in cli.iter_messages(d.entity, reverse=True, limit=None):
                    mdate = message.date.isoformat() if message.date else ""
                    if message.reply_markup and hasattr(message.reply_markup, 'rows'):
                        for row in message.reply_markup.rows:
                            for btn in row.buttons:
                                if hasattr(btn, 'url') and btn.url:
                                    s_ep, e_ep, formatted_range = parse_range_numbers(getattr(btn, 'text', ''))
                                    if s_ep is not None:
                                        raw_channel_items.append({
                                            "message_id": message.id,
                                            "message_date": mdate,
                                            "start_ep": s_ep, "end_ep": e_ep,
                                            "range_label": formatted_range,
                                            "shortlink": normalize_shortlink(btn.url),
                                            "bot_link": normalize_bot_link(btn.url)
                                        })

                    text = message.text or ""
                    b_m = BOT_RE.search(text)
                    s_m = SHORTLINK_RE.search(text)
                    if b_m or s_m:
                        rng_m = re.search(r'(\d+\s*[-–]\s*\d+)', text)
                        brange = rng_m.group(1) if rng_m else "01-10"
                        s_ep, e_ep, formatted_range = parse_range_numbers(brange)
                        if s_ep is not None:
                            raw_channel_items.append({
                                "message_id": message.id,
                                "message_date": mdate,
                                "start_ep": s_ep, "end_ep": e_ep,
                                "range_label": formatted_range,
                                "shortlink": normalize_shortlink(s_m.group(0)) if s_m else "N/A",
                                "bot_link": normalize_bot_link(b_m.group(0)) if b_m else "N/A"
                            })
            except Exception as e:
                print(f"⚠️ Error scanning channel {cname}: {e}", flush=True)

            if not raw_channel_items:
                save_skipped_channel(cid, cname, reason="no_links_found")
                continue

            has_any_shortlink = any(i["shortlink"] != "N/A" and i["shortlink"] for i in raw_channel_items)
            if not has_any_shortlink:
                save_skipped_channel(cid, cname, reason="only_free_bot_links_no_shortlinks")
                continue

            # Deduplicate by range
            unique_ranges = {}
            for item in raw_channel_items:
                unique_ranges[(item["start_ep"], item["end_ep"])] = item
            ordered_story_items = sorted(unique_ranges.values(), key=lambda x: x["start_ep"])

            # Resolve pending
            pending_items = []
            for item in ordered_story_items:
                if item["bot_link"] == "N/A" and item["shortlink"] != "N/A":
                    if item["shortlink"] in MASTER_RESOLVED_CACHE:
                        item["bot_link"] = MASTER_RESOLVED_CACHE[item["shortlink"]]
                    else:
                        pending_items.append(item)

            if pending_items:
                print(f"⚡ [{idx}/{len(channel_targets)}] '{cname}' -> Resolving {len(pending_items)} pending links...", flush=True)
                for p_item in pending_items:
                    res_bot = await resolve_one_shortlink(p, p_item["shortlink"])
                    if res_bot:
                        p_item["bot_link"] = res_bot
                        total_resolved_this_run += 1
                    await asyncio.sleep(1.0)

            # Append to master SQL file
            append_resolved_to_sql_file(cid, cname, ordered_story_items)
            total_channels_processed += 1

            if idx % 10 == 0:
                save_cache_to_disk()

    # Final cache save
    save_cache_to_disk()

    # Disconnect clients safely
    for cli in clients:
        try:
            await cli.disconnect()
        except Exception:
            pass

    print("\n" + "=" * 90, flush=True)
    print(f"🏆 GITHUB ACTIONS RUN COMPLETE: {total_channels_processed} channels processed | {total_resolved_this_run} new links resolved!", flush=True)
    print("=" * 90 + "\n", flush=True)


if __name__ == "__main__":
    asyncio.run(run_batch_harvest_and_resolve())
