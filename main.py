import asyncio
import datetime
import os
import re
import sqlite3
import sys
from collections import defaultdict
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import KeyboardButtonUrl

sys.stdout.reconfigure(encoding='utf-8')

# Configuration from Environment Variables
API_ID = int(os.environ.get("API_ID", "36198115"))
API_HASH = os.environ.get("API_HASH", "ce040e05f933e3e0a811f186c3d5d3bb")
SESSION_STR = os.environ.get("TELEGRAM_STRING_SESSION", "1BVtsOJoBu79FGJDwT08NrlugEVjBbtOhq1Efnp2XxTJZJgwW_QZnhDnAW_gCxrdnf6p63BgH0VCRsGwBMe7DYoEoDIaq0WztDhZvYZ0YVZKwsvnafV5gGY53ouuGeEzDI9hVjgSjcSWKXJAx5bdT3SVKsNyNOqxivxr5VMP4s94YaCdZCV9RMM5qKIBlvFmFRqF9cilVU17bbsxGGkOsxYKy4dE5kv3tRsmSBipaMH4f1MXFgdN5C82kyknlFEm8ORSbnCp81_ms0Ye43Tnghuw2l-i9SKKeuNUQWZv8jSlEOMRfPKeqymbWci9fD50QyiwQLkw3d0dx6jxACG01g9ZzTYD7FYY=")
PORT = int(os.environ.get("PORT", "8080"))
FORWARD_TO_SAVED_MESSAGES = os.environ.get("FORWARD_TO_SAVED_MESSAGES", "true").lower() == "true"

DB_PATH = "live_harvest.db"

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
    'syl': "Sylvia (English) •|Pocket FM|•"
}

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
    conn.commit()
    conn.close()

async def notify_user(client, text):
    if not FORWARD_TO_SAVED_MESSAGES or not client:
        return
    try:
        await client.send_message("me", text)
    except Exception as e:
        pass

async def process_and_store_link(client, cid, cname, mid, mdate, raw_range, surl, burl):
    cname = clean_story_title(cname)
    if not cname:
        return
        
    s_ep, e_ep, formatted_range = parse_range_numbers(raw_range)
    if s_ep is None or e_ep is None:
        return

    surl = normalize_shortlink(surl)
    burl = normalize_bot_link(burl)
    
    if surl == "N/A" and burl == "N/A":
        return

    is_10ep = 1 if (e_ep - s_ep >= 8) else 0
    status = "RESOLVED" if burl != "N/A" else "PENDING"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    superseded_list = []

    # 1. 10-Ep Consolidation & Fragment Superseding Logic
    if is_10ep:
        cursor.execute("""
            SELECT id, range_label, start_ep, end_ep FROM `live_harvest`
            WHERE channel_name = ? AND start_ep >= ? AND end_ep <= ? AND (end_ep - start_ep) < 8 AND status != 'SUPERSEDED'
        """, (cname, s_ep, e_ep))
        covered_fragments = cursor.fetchall()
        
        for frag_id, f_label, f_s, f_e in covered_fragments:
            cursor.execute("""
                UPDATE `live_harvest` 
                SET status = 'SUPERSEDED', superseded_by = ? 
                WHERE id = ?
            """, (formatted_range, frag_id))
            superseded_list.append(f_label)

    else:
        cursor.execute("""
            SELECT range_label FROM `live_harvest`
            WHERE channel_name = ? AND start_ep <= ? AND end_ep >= ? AND (end_ep - start_ep) >= 8 AND status != 'SUPERSEDED'
        """, (cname, s_ep, e_ep))
        enclosing_batch = cursor.fetchone()
        if enclosing_batch:
            status = "SUPERSEDED"
            superseded_by = enclosing_batch[0]
        else:
            superseded_by = None

    inserted = False
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
        conn.commit()
        inserted = True
    except Exception as e:
        pass
    finally:
        conn.close()

    if inserted:
        target_link = burl if burl != "N/A" else surl
        type_icon = "📦 [10-EP BATCH]" if is_10ep else "🔹 [FRAGMENT]"
        log_msg = f"{type_icon} <b>{cname}</b>\n• Range: <code>{formatted_range}</code>\n• Link: {target_link}\n• Status: <b>{status}</b>"
        
        if superseded_list:
            log_msg += f"\n• 🗑️ <i>Superseded earlier fragments: {', '.join(superseded_list)}</i>"
            
        print(f"[{now_str}] {type_icon} {cname} [{formatted_range}] -> {target_link} ({status})", flush=True)
        if status != "SUPERSEDED":
            await notify_user(client, log_msg)

async def extract_message_links(client, message, cid, cname):
    if not message:
        return
    mid = message.id
    mdate = message.date.isoformat() if message.date else ""
    text = message.text or ""
    
    # 1. Inline keyboard buttons
    if message.reply_markup and hasattr(message.reply_markup, 'rows'):
        for row in message.reply_markup.rows:
            for btn in row.buttons:
                if hasattr(btn, 'url') and btn.url:
                    label = getattr(btn, 'text', '')
                    url = btn.url
                    b_m = BOT_RE.search(url)
                    s_m = SHORTLINK_RE.search(url)
                    burl = b_m.group(0) if b_m else "N/A"
                    surl = s_m.group(0) if s_m else "N/A"
                    if burl != "N/A" or surl != "N/A":
                        await process_and_store_link(client, cid, cname, mid, mdate, label, surl, burl)

    # 2. Text urls
    b_m = BOT_RE.search(text)
    s_m = SHORTLINK_RE.search(text)
    if b_m or s_m:
        burl = b_m.group(0) if b_m else "N/A"
        surl = s_m.group(0) if s_m else "N/A"
        rng_m = re.search(r'(\d+\s*[-–]\s*\d+)', text)
        brange = rng_m.group(1) if rng_m else "01-10"
        await process_and_store_link(client, cid, cname, mid, mdate, brange, surl, burl)

# HTTP Server Routes for Render Health Checks & API
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
        "service": "CODEX Telegram Live Link Watcher Daemon",
        "total_captured": total,
        "unique_stories": stories,
        "active_resolved": resolved,
        "active_pending": pending,
        "superseded_fragments": superseded,
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

async def start_http_server():
    app = web.Application()
    app.router.add_get('/', handle_root)
    app.router.add_get('/health', handle_health)
    app.router.add_get('/links', handle_links)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"🌐 HTTP Health & API Server listening on port {PORT}", flush=True)

async def main():
    print("=========================================================================================", flush=True)
    print("🤖 STARTING CODEX TELEGRAM LIVE WATCHER CLOUD DAEMON (24/7 UPTIME)", flush=True)
    print("=========================================================================================", flush=True)
    
    init_db()
    
    # 1. Start HTTP keep-alive server for Render
    await start_http_server()
    
    # 2. Connect Telethon String Session
    client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH, timeout=15, auto_reconnect=True)
    await client.connect()
    
    if not await client.is_user_authorized():
        print("❌ Telethon String Session not authorized!", flush=True)
        return

    me = await client.get_me()
    print(f"✅ Connected & Authorized as: {me.first_name} (+{me.phone})", flush=True)
    
    dialogs = await client.get_dialogs()
    joined_channels = [d for d in dialogs if d.is_channel]
    print(f"📡 Monitoring {len(joined_channels)} joined story channels in real time...", flush=True)
    
    channel_entities = {}
    for d in joined_channels:
        clean_id = re.sub(r'^-?100', '', str(d.id))
        clean_id = re.sub(r'^-', '', clean_id)
        cname = clean_story_title(d.title)
        if cname:
            channel_entities[d.id] = (clean_id, cname)

    print(f"⚡ Performing initial bootstrap scan across {len(channel_entities)} story channels...", flush=True)
    for d in joined_channels:
        if d.id in channel_entities:
            clean_id, cname = channel_entities[d.id]
            try:
                async for message in client.iter_messages(d.entity, limit=5):
                    await extract_message_links(client, message, clean_id, cname)
            except Exception:
                pass

    print("👀 Live Listener ACTIVE. Watching for incoming & edited drops 24/7...\n", flush=True)

    @client.on(events.NewMessage)
    async def handler_new_message(event):
        chat_id = event.chat_id
        if chat_id in channel_entities:
            cid, cname = channel_entities[chat_id]
            await extract_message_links(client, event.message, cid, cname)

    @client.on(events.MessageEdited)
    async def handler_message_edited(event):
        chat_id = event.chat_id
        if chat_id in channel_entities:
            cid, cname = channel_entities[chat_id]
            await extract_message_links(client, event.message, cid, cname)

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
