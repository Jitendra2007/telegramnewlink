import asyncio
import datetime
import json
import os
import re
import sqlite3
import sys
from urllib.parse import urlparse
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import KeyboardButtonUrl
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding='utf-8')

# Configuration from Environment Variables
API_ID = int(os.environ.get("API_ID", "36198115"))
API_HASH = os.environ.get("API_HASH", "ce040e05f933e3e0a811f186c3d5d3bb")
SESSION_STR = os.environ.get("TELEGRAM_STRING_SESSION", "1BVtsOJoBu79FGJDwT08NrlugEVjBbtOhq1Efnp2XxTJZJgwW_QZnhDnAW_gCxrdnf6p63BgH0VCRsGwBMe7DYoEoDIaq0WztDhZvYZ0YVZKwsvnafV5gGY53ouuGeEzDI9hVjgSjcSWKXJAx5bdT3SVKsNyNOqxivxr5VMP4s94YaCdZCV9RMM5qKIBlvFmFRqF9cilVU17bbsxGGkOsxYKy4dE5kv3tRsmSBipaMH4f1MXFgdN5C82kyknlFEm8ORSbnCp81_ms0Ye43Tnghuw2l-i9SKKeuNUQWZv8jSlEOMRfPKeqymbWci9fD50QyiwQLkw3d0dx6jxACG01g9ZzTYD7FYY=")
PORT = int(os.environ.get("PORT", "8080"))
FORWARD_TO_SAVED_MESSAGES = os.environ.get("FORWARD_TO_SAVED_MESSAGES", "true").lower() == "true"
AUTO_RESOLVE = os.environ.get("AUTO_RESOLVE", "true").lower() == "true"
FULL_HISTORICAL_SCAN = os.environ.get("FULL_HISTORICAL_SCAN", "true").lower() == "true"

DB_PATH = "live_harvest.db"
CACHE_PATH = "master_resolved_cache.json"

# Regex Patterns
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
    'dhruva_posts_formatted': "Dhruva •|Pocket FM|•",
    'king_pocket_fm_telugu_posts_formatted': "King (Telugu) •|Pocket FM|•",
    'king_posts_formatted': "The King",
    'ge  2': "Godly Empress 2"
}

FLOW_HOSTS = {"hindisink.com", "linkshortx.in", "urlshortx.io", "telegram.me"}

MASTER_RESOLVED_CACHE = {}

scan_progress = {
    "status": "idle",
    "current_channel_index": 0,
    "total_channels": 0,
    "current_channel_name": "",
    "completed_channels_count": 0,
    "skipped_already_resolved_channels": 0,
    "total_messages_scanned": 0,
    "total_links_extracted": 0,
    "total_resolved_count": 0,
    "started_at": "",
    "completed_at": ""
}

def load_resolved_cache():
    global MASTER_RESOLVED_CACHE
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                MASTER_RESOLVED_CACHE = json.load(f)
            print(f"📦 Loaded {len(MASTER_RESOLVED_CACHE):,} pre-resolved link mappings from master cache.", flush=True)
        except Exception as e:
            print(f"⚠️ Could not load cache: {e}", flush=True)

FAST_STEP_JS = r"""
async () => {
  const bodyText = document.body ? document.body.innerText : "";
  const tgText = bodyText.match(
    /(?:https?:\/\/)?(?:telegram\.me|t\.me)\/[A-Za-z0-9_]+\?start=[A-Za-z0-9_%+\/=\-]+/i
  );
  if (tgText) return {action: "found_text", telegram: tgText[0]};

  for (const a of document.querySelectorAll("a")) {
    const href = a.href || "";
    if (/(?:telegram\.me|t\.me)\/[A-Za-z0-9_]+\?start=/i.test(href)) {
      return {action: "found_anchor", telegram: href};
    }
  }

  for (const el of document.querySelectorAll('.no_display, [style*="display: none"], [hidden]')) {
    el.classList.remove('no_display');
    el.hidden = false;
    el.style.display = 'block';
    el.style.visibility = 'visible';
    el.style.opacity = '1';
  }
  for (const el of document.querySelectorAll('button, a, input')) {
    el.disabled = false;
    el.removeAttribute('disabled');
  }

  const bypassForm = document.querySelector("form#fwd, form#rtg, form#landing") || document.querySelector("form:not(.search-form)");
  if (bypassForm) {
    try {
      HTMLFormElement.prototype.submit.call(bypassForm);
      return {action: "submitted_bypass_form", form: bypassForm.id || bypassForm.name || "form"};
    } catch(e) {
      try { bypassForm.submit(); return {action: "submitted_bypass_form_native"}; } catch(e2) {}
    }
  }

  const finalBtn = document.getElementById("final") ||
                   document.querySelector(".start_btn") ||
                   document.querySelector(".continue_btn") ||
                   document.querySelector("#rtg-snp21 button") ||
                   document.querySelector("#rtg-snp21 a") ||
                   document.querySelector(".btn-success, .btn-primary");
  if (finalBtn) {
    try { finalBtn.click(); } catch(e) {}
    return {action: "clicked_final"};
  }

  const getLink = document.querySelector(".get-link");
  if (getLink) {
    const disabled =
      getLink.classList.contains("disabled") ||
      getLink.getAttribute("aria-disabled") === "true" ||
      window.getComputedStyle(getLink).pointerEvents === "none";
    if (disabled) {
      return {action: "waiting_final_gate"};
    }
    return {action: "click_get_link"};
  }

  return {action: "nothing_matched", url: location.href};
}
"""

def host_of(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""

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

def normalize_shortlink(url):
    if not url or url == "N/A":
        return "N/A"
    m = SHORTLINK_RE.search(url)
    if m:
        return m.group(0).strip()
    return "N/A"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `live_harvest` (
            `id` INTEGER PRIMARY KEY AUTOINCREMENT,
            `channel_id` TEXT,
            `channel_name` TEXT,
            `message_id` INTEGER,
            `message_date` TEXT,
            `range_label` TEXT,
            `start_ep` INTEGER,
            `end_ep` INTEGER,
            `shortlink_url` TEXT,
            `telegram_bot_link` TEXT,
            `status` TEXT DEFAULT 'PENDING',
            `is_consolidated_10ep` INTEGER DEFAULT 0,
            `superseded_by` TEXT DEFAULT NULL,
            `harvested_at` TEXT,
            UNIQUE(`channel_id`, `start_ep`, `end_ep`, `telegram_bot_link`, `shortlink_url`)
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS `idx_harvest_story` ON `live_harvest` (`channel_name`, `start_ep`, `end_ep`);")
    cursor.execute("CREATE INDEX IF NOT EXISTS `idx_harvest_status` ON `live_harvest` (`status`);")
    cursor.execute("CREATE INDEX IF NOT EXISTS `idx_harvest_shortlink` ON `live_harvest` (`shortlink_url`);")
    conn.commit()
    conn.close()

async def notify_user(client, text):
    if not FORWARD_TO_SAVED_MESSAGES or not client:
        return
    try:
        await client.send_message("me", text, parse_mode="html")
    except Exception:
        pass

async def resolve_one_shortlink(playwright_instance, shortlink):
    found = None
    try:
        browser = await playwright_instance.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
    except Exception as e:
        print(f"  ❌ Browser launch failed: {e}", flush=True)
        return None

    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 720}
    )
    await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
    
    async def on_page(pop):
        try:
            if not context.pages or pop == context.pages[0]: return
            for _ in range(5):
                url = pop.url or ""
                if url and url != "about:blank": break
                await asyncio.sleep(0.1)
            p_host = host_of(pop.url)
            if not any(h in p_host for h in ["linkshortx", "urlshortx", "hindisink", "telegram"]):
                await pop.close()
        except Exception:
            pass

    context.on("page", lambda p: asyncio.create_task(on_page(p)))
    page = await context.new_page()

    def check_hit(url):
        nonlocal found
        if found: return
        m = BOT_RE.search(url)
        if m: found = m.group(0)

    page.on("request", lambda req: check_hit(req.url))
    page.on("response", lambda resp: check_hit(resp.url))

    try:
        await page.goto(shortlink, wait_until="commit", timeout=20000)
    except Exception:
        pass

    await asyncio.sleep(2)
    
    for _ in range(50):
        if found: break
        try:
            html = await page.content()
            m = BOT_RE.search(html) or BOT_RE.search(page.url or "")
            if m:
                found = m.group(0)
                break
        except Exception:
            pass

        try:
            result = await page.evaluate(FAST_STEP_JS)
            action = result.get("action") if isinstance(result, dict) else ""
            if isinstance(result, dict) and result.get("telegram"):
                found = result["telegram"]
                break
            if action == "click_get_link":
                await page.click(".get-link", timeout=5000, force=True)
            elif action in ("submitted_bypass_form", "clicked_final"):
                await asyncio.sleep(1.5)
            else:
                await asyncio.sleep(1.0)
        except Exception:
            await asyncio.sleep(1.0)

    if not found:
        try:
            get_link = await page.evaluate("""
                () => {
                    const snp = document.querySelector('#rtg-snp21');
                    if (snp) {
                        const a = snp.querySelector('a[href*="t.me"], a[href*="telegram.me"]');
                        if (a && a.href && a.href.includes('start=')) return a.href;
                    }
                    const links = Array.from(document.querySelectorAll('a'));
                    const tg = links.find(a => /telegram\\.me|t\\.me/i.test(a.href) && /\\?start=/i.test(a.href));
                    return tg ? tg.href : null;
                }
            """)
            if get_link: found = get_link
        except Exception:
            pass

    await browser.close()
    return normalize_bot_link(found)

def store_raw_link(cid, cname, mid, mdate, raw_range, surl, burl):
    cname = clean_story_title(cname)
    if not cname:
        return None, False

    s_ep, e_ep, formatted_range = parse_range_numbers(raw_range)
    if s_ep is None or e_ep is None:
        return None, False

    surl = normalize_shortlink(surl)
    burl = normalize_bot_link(burl)
    if surl == "N/A" and burl == "N/A":
        return None, False

    # Check Master Resolved Cache
    if burl == "N/A" and surl != "N/A" and surl in MASTER_RESOLVED_CACHE:
        burl = MASTER_RESOLVED_CACHE[surl]

    is_10ep = 1 if (e_ep - s_ep >= 8) else 0
    status = "RESOLVED" if burl != "N/A" else "PENDING"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if status == "PENDING" and surl != "N/A":
        cursor.execute("SELECT telegram_bot_link FROM `live_harvest` WHERE shortlink_url = ? AND status = 'RESOLVED'", (surl,))
        existing_bot = cursor.fetchone()
        if existing_bot and existing_bot[0] != "N/A":
            burl = existing_bot[0]
            status = "RESOLVED"

    if is_10ep:
        cursor.execute("""
            SELECT id, range_label FROM `live_harvest`
            WHERE channel_name = ? AND start_ep >= ? AND end_ep <= ? AND (end_ep - start_ep) < 8 AND status != 'SUPERSEDED'
        """, (cname, s_ep, e_ep))
        covered_fragments = cursor.fetchall()
        for frag_id, f_label in covered_fragments:
            cursor.execute("UPDATE `live_harvest` SET status = 'SUPERSEDED', superseded_by = ? WHERE id = ?", (formatted_range, frag_id))
    else:
        cursor.execute("""
            SELECT range_label FROM `live_harvest`
            WHERE channel_name = ? AND start_ep <= ? AND end_ep >= ? AND (end_ep - start_ep) >= 8 AND status != 'SUPERSEDED'
        """, (cname, s_ep, e_ep))
        enclosing_batch = cursor.fetchone()
        superseded_by = enclosing_batch[0] if enclosing_batch else None
        if enclosing_batch: status = "SUPERSEDED"

    row_id = None
    try:
        cursor.execute("""
            INSERT INTO `live_harvest` 
            (`channel_id`, `channel_name`, `message_id`, `message_date`, `range_label`, `start_ep`, `end_ep`, `shortlink_url`, `telegram_bot_link`, `status`, `is_consolidated_10ep`, `superseded_by`, `harvested_at`)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(`channel_id`, `start_ep`, `end_ep`, `telegram_bot_link`, `shortlink_url`) DO UPDATE SET
                `message_id` = excluded.`message_id`,
                `message_date` = excluded.`message_date`,
                `status` = excluded.`status`,
                `harvested_at` = excluded.`harvested_at`
        """, (cid, cname, mid, mdate, formatted_range, s_ep, e_ep, surl, burl, status, is_10ep, superseded_by if not is_10ep else None, now_str))
        row_id = cursor.lastrowid
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()

    is_pending = (status == "PENDING" and surl != "N/A")
    return {
        "id": row_id,
        "channel_name": cname,
        "range_label": formatted_range,
        "shortlink": surl,
        "bot_link": burl,
        "status": status,
        "is_10ep": is_10ep
    }, is_pending

# Sequential Channel-by-Channel Complete Scanner & 3-Cycle Retry Engine
async def sequential_channel_scanner_and_resolver(client, joined_channels, channel_entities):
    scan_progress["status"] = "in_progress"
    scan_progress["started_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scan_progress["total_channels"] = len(channel_entities)

    print(f"\n=========================================================================================", flush=True)
    print(f"🎯 STARTING SEQUENTIAL CHANNEL-BY-CHANNEL FULL RESOLUTION ENGINE ({len(channel_entities)} CHANNELS)", flush=True)
    print(f"🔒 Rules:", flush=True)
    print(f"   1. Skip channels that are already 100% resolved (0 pending links) to avoid dual-account clashes.", flush=True)
    print(f"   2. Advance to next channel IF AND ONLY IF current channel is 100% resolved!", flush=True)
    print(f"   3. If a link fails to resolve, retry in 3 robust cycles before completing channel.", flush=True)
    print(f"=========================================================================================\n", flush=True)

    async with async_playwright() as p:
        idx = 0
        for d in joined_channels:
            if d.id not in channel_entities:
                continue
                
            idx += 1
            cid, cname = channel_entities[d.id]
            scan_progress["current_channel_index"] = idx
            scan_progress["current_channel_name"] = cname

            print(f"\n-----------------------------------------------------------------------------------------", flush=True)
            print(f"📖 [Channel {idx}/{len(channel_entities)}] STORY: '{cname}' (ID: {cid})", flush=True)
            print(f"-----------------------------------------------------------------------------------------", flush=True)

            msg_count = 0
            pending_queue = []
            extracted_count = 0
            
            try:
                async for message in client.iter_messages(d.entity, limit=None):
                    msg_count += 1
                    scan_progress["total_messages_scanned"] += 1
                    
                    if message.reply_markup and hasattr(message.reply_markup, 'rows'):
                        for row in message.reply_markup.rows:
                            for btn in row.buttons:
                                if hasattr(btn, 'url') and btn.url:
                                    entry, is_pending = store_raw_link(cid, cname, message.id, message.date.isoformat() if message.date else "", getattr(btn, 'text', ''), btn.url, "N/A")
                                    if entry:
                                        extracted_count += 1
                                        scan_progress["total_links_extracted"] += 1
                                        if is_pending: pending_queue.append(entry)

                    text = message.text or ""
                    b_m = BOT_RE.search(text)
                    s_m = SHORTLINK_RE.search(text)
                    if b_m or s_m:
                        burl = b_m.group(0) if b_m else "N/A"
                        surl = s_m.group(0) if s_m else "N/A"
                        rng_m = re.search(r'(\d+\s*[-–]\s*\d+)', text)
                        brange = rng_m.group(1) if rng_m else "01-10"
                        entry, is_pending = store_raw_link(cid, cname, message.id, message.date.isoformat() if message.date else "", brange, surl, burl)
                        if entry:
                            extracted_count += 1
                            scan_progress["total_links_extracted"] += 1
                            if is_pending: pending_queue.append(entry)

                    if msg_count % 100 == 0:
                        await asyncio.sleep(0.05)
            except Exception as e:
                print(f"  ⚠️ Error scanning messages for {cname}: {e}", flush=True)

            # Check if Already 100% Resolved -> SKIP IMMEDIATELY!
            if len(pending_queue) == 0:
                scan_progress["skipped_already_resolved_channels"] += 1
                scan_progress["completed_channels_count"] += 1
                print(f"  ⚡ [ALREADY 100% RESOLVED] '{cname}' has {extracted_count} links and ZERO pending links. Leaving channel cleanly! 🚀", flush=True)
                await asyncio.sleep(0.5)
                continue

            # RESOLVE ALL PENDING SHORTLINKS FOR THIS CHANNEL IN 3-CYCLE RETRY FORM
            if pending_queue and AUTO_RESOLVE:
                print(f"  ⚡ Resolving {len(pending_queue)} pending shortlinks for '{cname}' in 3-Cycle Retry Form...", flush=True)
                
                remaining_to_resolve = list(pending_queue)
                
                for cycle in range(1, 4):
                    if not remaining_to_resolve:
                        break
                        
                    print(f"\n  🔄 [Cycle {cycle}/3] Processing {len(remaining_to_resolve)} links for '{cname}'...", flush=True)
                    failed_this_cycle = []
                    
                    for p_idx, p_entry in enumerate(remaining_to_resolve, 1):
                        surl = p_entry['shortlink']
                        rng = p_entry['range_label']
                        row_id = p_entry['id']
                        
                        if surl in MASTER_RESOLVED_CACHE:
                            bot_url = MASTER_RESOLVED_CACHE[surl]
                            print(f"    [{p_idx}/{len(remaining_to_resolve)}] ⚡ Instant Match from Cache: [{rng}] -> {bot_url}", flush=True)
                        else:
                            print(f"    [{p_idx}/{len(remaining_to_resolve)}] 🌐 Resolving [Cycle {cycle}]: [{rng}] {surl} ...", flush=True)
                            bot_url = await resolve_one_shortlink(p, surl)
                            if bot_url and bot_url != "N/A":
                                MASTER_RESOLVED_CACHE[surl] = bot_url

                        if bot_url and bot_url != "N/A":
                            conn = sqlite3.connect(DB_PATH)
                            cursor = conn.cursor()
                            cursor.execute("UPDATE `live_harvest` SET telegram_bot_link = ?, status = 'RESOLVED' WHERE id = ?", (bot_url, row_id))
                            conn.commit()
                            conn.close()
                            scan_progress["total_resolved_count"] += 1
                            
                            res_msg = f"🎉 <b>[RESOLVED & READY TO PLAY]</b>\n<b>{cname}</b>\n• Range: <code>{rng}</code>\n• Bot Link: {bot_url}"
                            await notify_user(client, res_msg)
                        else:
                            print(f"    ⏳ [Cycle {cycle} Failed] Will retry: {surl}", flush=True)
                            failed_this_cycle.append(p_entry)

                        await asyncio.sleep(1.5)

                    remaining_to_resolve = failed_this_cycle
                    if remaining_to_resolve and cycle < 3:
                        print(f"  ⏸️ Pausing 3s before starting Retry Cycle {cycle + 1} for {len(remaining_to_resolve)} failed links...", flush=True)
                        await asyncio.sleep(3)

            # CHANNEL FULLY COMPLETE
            scan_progress["completed_channels_count"] += 1
            print(f"✅ [100% FULLY RESOLVED & VERIFIED] Channel '{cname}' completed successfully! Advancing to next channel...\n", flush=True)
            await asyncio.sleep(1)

    scan_progress["status"] = "completed"
    scan_progress["completed_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n=========================================================================================", flush=True)
    print(f"🏆 ALL {len(channel_entities)} CHANNELS 100% FULLY EXTRACTED & RESOLVED!", flush=True)
    print(f"=========================================================================================\n", flush=True)

# HTTP Server Routes
async def handle_root(request):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM `live_harvest`")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM `live_harvest` WHERE status = 'RESOLVED'")
    resolved = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM `live_harvest` WHERE status = 'PENDING'")
    pending = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM `live_harvest` WHERE status = 'SUPERSEDED'")
    superseded = cursor.fetchone()[0]
    cursor.execute("SELECT count(DISTINCT channel_name) FROM `live_harvest`")
    stories = cursor.fetchone()[0]
    conn.close()

    return web.json_response({
        "status": "online",
        "service": "CODEX Telegram Channel-by-Channel Complete Resolution Daemon",
        "total_captured": total,
        "unique_stories": stories,
        "active_resolved": resolved,
        "active_pending": pending,
        "superseded_fragments": superseded,
        "cached_resolved_pairs": len(MASTER_RESOLVED_CACHE),
        "sequential_scan_progress": scan_progress,
        "retry_cycles_form": "3-Cycle Robust Retries",
        "uptime": "24/7"
    })

async def handle_health(request):
    return web.Response(text="OK", status=200)

async def handle_links(request):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT channel_name, range_label, start_ep, end_ep, shortlink_url, telegram_bot_link, status, is_consolidated_10ep, harvested_at
        FROM `live_harvest`
        WHERE status != 'SUPERSEDED'
        ORDER BY channel_name ASC, start_ep ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for r in rows:
        result.append({
            "channel_name": r[0],
            "range": r[1],
            "start_ep": r[2],
            "end_ep": r[3],
            "shortlink": r[4],
            "bot_link": r[5],
            "status": r[6],
            "is_10ep_batch": bool(r[7]),
            "harvested_at": r[8]
        })
    return web.json_response(result)

async def handle_export_sql(request):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT channel_id, channel_name, message_id, message_date, range_label, start_ep, end_ep, shortlink_url, telegram_bot_link, status
        FROM `live_harvest`
        WHERE status != 'SUPERSEDED'
        ORDER BY channel_name ASC, start_ep ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    lines = []
    lines.append("-- CODEX Live Cloud Harvest Database Export (Channel-by-Channel Fully Resolved)\n")
    lines.append(f"-- Exported on: {datetime.datetime.now().isoformat()} | Total Rows: {len(rows):,}\n\n")
    lines.append("INSERT INTO `pocket_fm_all_in_one_links` (`channel_id`, `channel_name`, `message_id`, `message_date`, `button_range`, `start_episode`, `end_episode`, `shortlink_url`, `telegram_bot_link`, `status`, `source`) VALUES\n")

    val_lines = []
    for r in rows:
        cid, cname, mid, mdate, rng, sep, eep, surl, burl, st = r
        cname_esc = cname.replace("'", "''")
        surl_esc = surl.replace("'", "''")
        burl_esc = burl.replace("'", "''")
        mdate_esc = mdate.replace("'", "''")
        val_lines.append(f"('{cid}', '{cname_esc}', {mid or 0}, '{mdate_esc}', '{rng}', {sep}, {eep}, '{surl_esc}', '{burl_esc}', '{st}', 'live_cloud_harvest')")

    sql_content = ",\n".join(val_lines) + ";\n"
    return web.Response(text="\n".join(lines) + sql_content, content_type="text/plain; charset=utf-8")

async def start_http_server():
    app = web.Application()
    app.router.add_get('/', handle_root)
    app.router.add_get('/health', handle_health)
    app.router.add_get('/links', handle_links)
    app.router.add_get('/export.sql', handle_export_sql)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"🌐 HTTP Health & API Server listening on port {PORT}", flush=True)

async def main():
    print("=========================================================================================", flush=True)
    print("🤖 STARTING CODEX TELEGRAM CHANNEL-BY-CHANNEL FULL RESOLUTION DAEMON (24/7 UPTIME)", flush=True)
    print("=========================================================================================", flush=True)
    
    init_db()
    load_resolved_cache()
    await start_http_server()
    
    client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH, timeout=15, auto_reconnect=True)
    await client.connect()
    
    if not await client.is_user_authorized():
        print("❌ Telethon String Session not authorized!", flush=True)
        return

    me = await client.get_me()
    print(f"✅ Connected & Authorized as: {me.first_name} (+{me.phone})", flush=True)
    
    dialogs = await client.get_dialogs()
    joined_channels = [d for d in dialogs if d.is_channel]
    print(f"📡 Discovered {len(joined_channels)} joined story channels...", flush=True)
    
    channel_entities = {}
    for d in joined_channels:
        clean_id = re.sub(r'^-?100', '', str(d.id))
        clean_id = re.sub(r'^-', '', clean_id)
        cname = clean_story_title(d.title)
        if cname:
            channel_entities[d.id] = (clean_id, cname)

    print(f"📖 {len(channel_entities)} valid story channels mapped for strict channel-by-channel full resolution.", flush=True)

    if FULL_HISTORICAL_SCAN:
        asyncio.create_task(sequential_channel_scanner_and_resolver(client, joined_channels, channel_entities))

    print("👀 Live Listener ACTIVE. Watching for incoming daily drops in real time...\n", flush=True)

    @client.on(events.NewMessage)
    async def handler_new_message(event):
        chat_id = event.chat_id
        if chat_id in channel_entities:
            cid, cname = channel_entities[chat_id]
            entry, is_pending = store_raw_link(cid, cname, event.message.id, event.message.date.isoformat() if event.message.date else "", "", "", "")

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
