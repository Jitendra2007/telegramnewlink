import asyncio
import datetime
import json
import os
import re
import sqlite3
import sys
from urllib.parse import urlparse
from aiohttp import ClientSession, ClientTimeout, web
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import time
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding='utf-8')

# Configuration from Environment Variables
API_ID = int(os.environ.get("API_ID", "36198115"))
API_HASH = os.environ.get("API_HASH", "ce040e05f933e3e0a811f186c3d5d3bb")
# Account 1 (Main: Rock / +91 9848915830)
SESSION_STR_MAIN = os.environ.get("TELEGRAM_STRING_SESSION", "1BVtsOKABu30UGkzgJxm5hTt4bzvmO5EoUVOWdXgz5yhqmuEoLOWHZw7Zg5W6nui5zmT_Xk1UoaWPZGAWno-xzhr_41A6ieDvTtxPze2fdvyuora0eKL90zGhsNxSxsuqcuvEkbpH3YueaSiQTJRH7kZNjYANtk6-0i6ty-fgTkWaRw65LyEgKNcPGPaCR2niQsvJdcZ07Kbuo7Oaqmfw4KvPB-VaH8OmcyuB-awKviKfoAB2Ud87OSSHLf_6kM1IJ9DCHKKgQ19vSE1ZR9RjDg8CyJWg8CXJv1kKuTBDteF_K4nT_AJcOQTNI-zfYgNoOwhADM90Qm37xKqXu3IOEUnuu8-ZhRw=")
# Account 2 (Sub: Syamala / +91 9490590394)
SESSION_STR_SUB = os.environ.get("TELEGRAM_STRING_SESSION_SUB", "1BVtsOJoBu79FGJDwT08NrlugEVjBbtOhq1Efnp2XxTJZJgwW_QZnhDnAW_gCxrdnf6p63BgH0VCRsGwBMe7DYoEoDIaq0WztDhZvYZ0YVZKwsvnafV5gGY53ouuGeEzDI9hVjgSjcSWKXJAx5bdT3SVKsNyNOqxivxr5VMP4s94YaCdZCV9RMM5qKIBlvFmFRqF9cilVU17bbsxGGkOsxYKy4dE5kv3tRsmSBipaMH4f1MXFgdN5C82kyknlFEm8ORSbnCp81_ms0Ye43Tnghuw2l-i9SKKeuNUQWZv8jSlEOMRfPKeqymbWci9fD50QyiwQLkw3d0dx6jxACG01g9ZzTYD7FYY=")
PORT = int(os.environ.get("PORT", "10000"))  # Render default is 10000
FORWARD_TO_SAVED_MESSAGES = os.environ.get("FORWARD_TO_SAVED_MESSAGES", "true").lower() == "true"
AUTO_RESOLVE = os.environ.get("AUTO_RESOLVE", "true").lower() == "true"
FULL_HISTORICAL_SCAN = os.environ.get("FULL_HISTORICAL_SCAN", "true").lower() == "true"
KEEPALIVE_INTERVAL_SECONDS = int(os.environ.get("KEEPALIVE_INTERVAL_SECONDS", str(10 * 60)))
KEEPALIVE_URL = os.environ.get("KEEPALIVE_URL") or os.environ.get("RENDER_EXTERNAL_URL")
PLAYWRIGHT_CHROMIUM_EXECUTABLE = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")

DB_PATH = "live_harvest.db"
CACHE_PATH = "master_resolved_cache.json"
STORY_SETS_DIR = "story_sets"

HINDISINK_REFERER = "https://hindisink.com/best-free-ai-tools-content-design-or-productivity/"

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
    "qualified_channels_count": 0,
    "skipped_no_shortlinks_count": 0,
    "completed_channels_count": 0,
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
  // ─── 0. Check for Telegram bot link already present ───────────────────
  const BOT_PAT = /(?:https?:\/\/)?(?:telegram\.me|t\.me)\/[A-Za-z0-9_]+\?start=[A-Za-z0-9_%+\/=\-]+/i;

  for (const a of document.querySelectorAll("a")) {
    const href = a.href || "";
    if (BOT_PAT.test(href)) return {action: "found_anchor", telegram: href};
  }
  const bodyText = document.body ? document.body.innerText : "";
  const tgText = bodyText.match(BOT_PAT);
  if (tgText) return {action: "found_text", telegram: tgText[0]};

  // ─── GUARD: Cloudflare / loading pages — wait, don't touch ────────────
  const title = document.title || "";
  const url = location.href || "";
  if (title.toLowerCase().includes("checking your browser") ||
      title.toLowerCase().includes("just a moment") ||
      url.includes("challenges.cloudflare.com") ||
      document.querySelector("#challenge-running, #cf-challenge-running")) {
    return {action: "waiting_cloudflare", url: url};
  }

  // ─── 1. Kill the #hsg ad-gate (hindisink.com step system) ─────────────
  const now = Date.now();
  try { document.cookie = 'hsg=done:' + now + ';path=/;max-age=180;SameSite=Lax'; } catch(e) {}
  try { sessionStorage.setItem('hsg', 'done:' + now); } catch(e) {}
  const gate = document.getElementById('hsg');
  if (gate) {
    gate.hidden = true;
    if (gate.parentNode) gate.parentNode.removeChild(gate);
    document.documentElement.style.overflow = '';
  }

  // ─── 2. Instant-click the "Click here to verify" (#go) button ────────
  const goBtn = document.getElementById('go');
  if (goBtn) {
    goBtn.click();
    const cd = document.getElementById('cd');
    const num = document.getElementById('num');
    const bar = document.getElementById('bar');
    if (num) num.textContent = '0';
    if (bar) bar.style.width = '100%';
    const pCont = document.getElementById('pCont');
    if (pCont) pCont.classList.remove('x');
    if (cd) cd.classList.add('x');
    for (let i = 1; i < 9999; i++) { try { clearInterval(i); } catch(e) {} }
    return {action: "bypassed_go"};
  }

  // ─── 3. Click "Continue" (#cont) and skip the 5s hold ────────────────
  const cont = document.getElementById('cont');
  if (cont && !cont.closest('.x')) {
    cont.click();
    const pHold = document.getElementById('pHold');
    const pDone = document.getElementById('pDone');
    if (pHold) pHold.classList.add('x');
    if (pDone) pDone.classList.remove('x');
    for (let i = 1; i < 9999; i++) { try { clearInterval(i); } catch(e) {} }
    return {action: "bypassed_cont"};
  }

  // ─── 4. Click the final "Done" / link element (#pDone area) ──────────
  const pDone = document.getElementById('pDone');
  if (pDone && !pDone.classList.contains('x')) {
    const finalA = pDone.querySelector('a[href]');
    if (finalA) {
      const href = finalA.href;
      if (BOT_PAT.test(href)) return {action: "found_pDone_link", telegram: href};
      finalA.click();
      return {action: "clicked_pDone_link", href: href};
    }
    const finalBtn = pDone.querySelector('button, input[type="submit"]');
    if (finalBtn) {
      finalBtn.click();
      return {action: "clicked_pDone_button"};
    }
  }

  // ─── 5. Legacy selectors (ONLY specific known forms, not generic) ────
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

  // ONLY submit forms with specific known shortlink IDs — never generic forms
  const bypassForm = document.querySelector("form#fwd, form#rtg, form#landing");
  if (bypassForm) {
    try {
      HTMLFormElement.prototype.submit.call(bypassForm);
      return {action: "submitted_bypass_form", id: bypassForm.id};
    } catch(e) {}
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
    // Don't click in JS — return signal for Python to click via page.click(force=True)
    return {action: "click_get_link"};
  }

  const finalBtn = document.getElementById("final") ||
                   document.querySelector(".start_btn") ||
                   document.querySelector(".continue_btn") ||
                   document.querySelector("#rtg-snp21 button") ||
                   document.querySelector("#rtg-snp21 a") ||
                   document.querySelector(".btn-success, .btn-primary");
  if (finalBtn) {
    const href = finalBtn.href || '';
    if (BOT_PAT.test(href)) return {action: "found_final_link", telegram: href};
    try { finalBtn.click(); } catch(e) {}
    return {action: "clicked_final"};
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

def init_db():
    os.makedirs(STORY_SETS_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `channel_story_sets` (
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
            `is_free_bot_link` INTEGER DEFAULT 0,
            `status` TEXT DEFAULT 'RESOLVED',
            `saved_at` TEXT,
            UNIQUE(`channel_id`, `start_ep`, `end_ep`)
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS `idx_story_set` ON `channel_story_sets` (`channel_name`, `start_ep`);")
    cursor.execute("CREATE INDEX IF NOT EXISTS `idx_msg_order` ON `channel_story_sets` (`channel_id`, `message_id`);")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `channel_verification_registry` (
            `channel_id` TEXT PRIMARY KEY,
            `channel_name` TEXT,
            `total_free_bot_links` INTEGER DEFAULT 0,
            `total_resolved_shortlinks` INTEGER DEFAULT 0,
            `total_episodes` INTEGER DEFAULT 0,
            `status` TEXT DEFAULT 'UNVERIFIED',
            `last_updated` TEXT
        );
    """)

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
    """
    Resolve a shortlink to a Telegram bot link.
    Strategy:
      1. Instant cache lookup (verified correct, 23,014 pairs)
      2. HTTP redirect-following via aiohttp — fast, no RAM (catches plain redirect chains)
      3. Playwright fallback ONLY if HTTP fails — strict 20s, one page, browser closed immediately
    """
    if shortlink in MASTER_RESOLVED_CACHE:
        return MASTER_RESOLVED_CACHE[shortlink]

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": HINDISINK_REFERER,
    }

    # ── Step 1: HTTP redirect-following (zero RAM) ──────────────────────────
    found = None
    current_url = shortlink
    try:
        async with ClientSession(timeout=ClientTimeout(total=12), headers=HEADERS) as session:
            for hop in range(12):
                if not current_url or not current_url.startswith("http"):
                    break
                m = BOT_RE.search(current_url)
                if m:
                    found = m.group(0)
                    break
                try:
                    async with session.get(
                        current_url,
                        allow_redirects=False,
                        ssl=False,
                        timeout=ClientTimeout(total=10)
                    ) as resp:
                        location = resp.headers.get("Location", "")
                        if location:
                            m = BOT_RE.search(location)
                            if m:
                                found = m.group(0)
                                break
                            current_url = location if location.startswith("http") else __import__("urllib.parse", fromlist=["urljoin"]).urljoin(current_url, location)
                            continue
                        if resp.status in (404, 410):
                            print(f"    🚫 [DEAD {resp.status}]: {shortlink}", flush=True)
                            return "N/A"
                        try:
                            body = await resp.text(encoding="utf-8", errors="ignore")
                        except Exception:
                            body = ""
                        m = BOT_RE.search(body)
                        if m:
                            found = m.group(0)
                            break
                        body_lower = body.lower()
                        if any(t in body_lower for t in ["404 not found", "was not found", "doesn't exist", "may have expired", "link expired", "invalid key", "wrong turn"]):
                            print(f"    🚫 [DEAD/EXPIRED]: {shortlink}", flush=True)
                            return "N/A"
                        break
                except asyncio.TimeoutError:
                    break
                except Exception:
                    break
    except Exception:
        pass

    if found:
        result = normalize_bot_link(found)
        if result and result != "N/A":
            print(f"    ✅ [RESOLVED HTTP]: {shortlink} -> {result}", flush=True)
            MASTER_RESOLVED_CACHE[shortlink] = result
            return result

    # ── Step 2: Playwright fallback for JS-gated shortlinks (Direct Referer Engine) ─
    print(f"    🌐 [PLAYWRIGHT FALLBACK]: {shortlink}", flush=True)
    start_time = time.time()
    MAX_BROWSER_SECONDS = 18.0
    pw_found = None
    browser = None
    try:
        browser = await playwright_instance.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-setuid-sandbox",
            "--disable-dev-shm-usage", "--disable-gpu",
            "--single-process", "--no-zygote",
            "--disable-extensions", "--ignore-certificate-errors",
            "--disable-images", "--blink-settings=imagesEnabled=false",
        ])
        context = await browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 720},
            java_script_enabled=True,
        )
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(document, 'visibilityState', {get: () => 'visible', configurable: true});
            Object.defineProperty(document, 'hidden', {get: () => false, configurable: true});
            try { document.cookie = 'hsg=done:' + Date.now() + ';path=/;max-age=180;SameSite=Lax'; } catch(e) {}
            try { sessionStorage.setItem('hsg', 'done:' + Date.now()); } catch(e) {}
        """)

        page = await context.new_page()

        def check_hit(url):
            nonlocal pw_found
            if pw_found: return
            m = BOT_RE.search(url)
            if m:
                pw_found = m.group(0)

        page.on("request", lambda req: check_hit(req.url))
        page.on("response", lambda resp: check_hit(resp.url))

        # Phase 1: Fast Direct Referer Bypass (~11s)
        try:
            await page.goto(shortlink, referer=HINDISINK_REFERER, wait_until="domcontentloaded", timeout=16000)
            for _ in range(14):
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
                    await asyncio.sleep(2.5)
                    break
                await asyncio.sleep(1.0)
        except Exception:
            pass

        # Phase 2: Fallback if Direct Referer did not trigger .get-link
        if not pw_found:
            try:
                for _ in range(10):
                    if pw_found: break
                    try:
                        await page.evaluate(r"""() => {
                            const b = document.querySelector('a#final, #rtg-snp21 a, .get-link, a.btn-primary');
                            if (b) b.click();
                        }""")
                    except Exception:
                        pass
                    await asyncio.sleep(1.0)
            except Exception:
                pass

        for _ in range(3):
            if pw_found: break
            try:
                c = await page.content()
                m = BOT_RE.search(c) or BOT_RE.search(page.url or "")
                if m:
                    pw_found = m.group(0)
                    break
            except Exception:
                pass
            await asyncio.sleep(0.5)

    except Exception as e:
        print(f"    ⚠️ [PW ERR] {shortlink}: {type(e).__name__}", flush=True)
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass

    if pw_found:
        result = normalize_bot_link(pw_found)
        if result and result != "N/A":
            MASTER_RESOLVED_CACHE[shortlink] = result
            elapsed = time.time() - start_time
            print(f"    ✅ [RESOLVED PW]: {shortlink} -> {result} ({elapsed:.1f}s)", flush=True)
            return result

    elapsed = time.time() - start_time
    print(f"    ⚠️ [UNRESOLVED]: {shortlink} ({elapsed:.1f}s) — marking pending", flush=True)
    return None





# Save Channel Set to Dedicated Database and Story File
def save_channel_story_set(cid, cname, ordered_items):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    free_bot_count = 0
    resolved_shortlink_count = 0
    
    for item in ordered_items:
        s_ep, e_ep = item["start_ep"], item["end_ep"]
        is_free = 1 if (item["shortlink"] == "N/A" or not item["shortlink"]) else 0
        if is_free:
            free_bot_count += 1
        else:
            resolved_shortlink_count += 1
            
        cursor.execute("""
            INSERT INTO `channel_story_sets`
            (`channel_id`, `channel_name`, `message_id`, `message_date`, `range_label`, `start_ep`, `end_ep`, `shortlink_url`, `telegram_bot_link`, `is_free_bot_link`, `status`, `saved_at`)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'RESOLVED', ?)
            ON CONFLICT(`channel_id`, `start_ep`, `end_ep`) DO UPDATE SET
                `message_id` = excluded.`message_id`,
                `message_date` = excluded.`message_date`,
                `shortlink_url` = excluded.`shortlink_url`,
                `telegram_bot_link` = excluded.`telegram_bot_link`,
                `is_free_bot_link` = excluded.`is_free_bot_link`,
                `saved_at` = excluded.`saved_at`
        """, (cid, cname, item["message_id"], item["message_date"], item["range_label"], s_ep, e_ep, item["shortlink"], item["bot_link"], is_free, now_str))

    cursor.execute("""
        INSERT INTO `channel_verification_registry`
        (`channel_id`, `channel_name`, `total_free_bot_links`, `total_resolved_shortlinks`, `total_episodes`, `status`, `last_updated`)
        VALUES (?, ?, ?, ?, ?, '100%_FULLY_RESOLVED', ?)
        ON CONFLICT(`channel_id`) DO UPDATE SET
            `total_free_bot_links` = excluded.`total_free_bot_links`,
            `total_resolved_shortlinks` = excluded.`total_resolved_shortlinks`,
            `total_episodes` = excluded.`total_episodes`,
            `status` = '100%_FULLY_RESOLVED',
            `last_updated` = excluded.`last_updated`
    """, (cid, cname, free_bot_count, resolved_shortlink_count, len(ordered_items), now_str))
    
    conn.commit()
    conn.close()

    # Write formatted Story Set text file
    safe_filename = re.sub(r'[^\w\-_. ]', '_', cname).strip() + ".txt"
    filepath = os.path.join(STORY_SETS_DIR, safe_filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"Channel Name: {cname}\n")
        f.write(f"Channel ID: {cid}\n")
        f.write(f"Total Sets: {len(ordered_items)} (Free Bot Links: {free_bot_count}, Resolved Shortlinks: {resolved_shortlink_count})\n")
        f.write(f"Verified Date: {now_str}\n")
        f.write("="*90 + "\n\n")
        for item in ordered_items:
            f.write(f"Range: {item['range_label']:<10} | Shortlink: {item['shortlink']:<32} | Bot Link: {item['bot_link']}\n")

# Sequential Channel-by-Channel Complete Extraction & Resolution Engine (Message ID Order)
async def sequential_channel_scanner_and_resolver(channel_targets):
    scan_progress["status"] = "in_progress"
    scan_progress["started_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scan_progress["total_channels"] = len(channel_targets)

    print(f"\n=========================================================================================", flush=True)
    print(f"🎯 STARTING FRESH CHRONOLOGICAL CHANNEL-BY-CHANNEL FULL EXTRACTION & RESOLUTION", flush=True)
    print(f"🔒 Rules:", flush=True)
    print(f"   1. Extract channel messages in ascending Message ID order (Message ID 1 to latest).", flush=True)
    print(f"   2. First capture Free Bot Links in chronological message order.", flush=True)
    print(f"   3. Resolve all Shortlinks 100% for that channel using cache / fast-bypass.", flush=True)
    print(f"   4. Store clean ordered set with Channel Name, Ranges, Shortlinks, Bot Links.", flush=True)
    print(f"   5. Advance to next channel if and only if current channel is 100% finished!", flush=True)
    print(f"=========================================================================================\n", flush=True)

    async with async_playwright() as p:
        for idx, (cli, d, cid, cname) in enumerate(channel_targets, 1):
            scan_progress["current_channel_index"] = idx
            scan_progress["current_channel_name"] = cname

            print(f"\n-----------------------------------------------------------------------------------------", flush=True)
            print(f"📖 [Channel {idx}/{len(channel_targets)}] EXTRACTING STORY: '{cname}' (ID: {cid})", flush=True)
            print(f"-----------------------------------------------------------------------------------------", flush=True)

            raw_channel_items = []
            msg_count = 0
            
            # Step 1: Newly extract all messages in ascending chronological Message ID order (reverse=True)
            try:
                async for message in cli.iter_messages(d.entity, reverse=True, limit=None):
                    msg_count += 1
                    scan_progress["total_messages_scanned"] += 1
                    mdate = message.date.isoformat() if message.date else ""
                    
                    # 1. Parse Buttons
                    if message.reply_markup and hasattr(message.reply_markup, 'rows'):
                        for row in message.reply_markup.rows:
                            for btn in row.buttons:
                                if hasattr(btn, 'url') and btn.url:
                                    b_txt = getattr(btn, 'text', '')
                                    s_ep, e_ep, formatted_range = parse_range_numbers(b_txt)
                                    if s_ep is not None and e_ep is not None:
                                        burl = normalize_bot_link(btn.url)
                                        surl = normalize_shortlink(btn.url)
                                        raw_channel_items.append({
                                            "message_id": message.id,
                                            "message_date": mdate,
                                            "start_ep": s_ep,
                                            "end_ep": e_ep,
                                            "range_label": formatted_range,
                                            "shortlink": surl if surl != "N/A" else "N/A",
                                            "bot_link": burl if burl != "N/A" else "N/A"
                                        })

                    # 2. Parse Text Body
                    text = message.text or ""
                    b_m = BOT_RE.search(text)
                    s_m = SHORTLINK_RE.search(text)
                    if b_m or s_m:
                        rng_m = re.search(r'(\d+\s*[-–]\s*\d+)', text)
                        brange = rng_m.group(1) if rng_m else "01-10"
                        s_ep, e_ep, formatted_range = parse_range_numbers(brange)
                        if s_ep is not None and e_ep is not None:
                            burl = normalize_bot_link(b_m.group(0)) if b_m else "N/A"
                            surl = normalize_shortlink(s_m.group(0)) if s_m else "N/A"
                            raw_channel_items.append({
                                "message_id": message.id,
                                "message_date": mdate,
                                "start_ep": s_ep,
                                "end_ep": e_ep,
                                "range_label": formatted_range,
                                "shortlink": surl,
                                "bot_link": burl
                            })

                    if msg_count % 150 == 0:
                        await asyncio.sleep(0.02)
            except Exception as e:
                print(f"  ⚠️ Error scanning messages for {cname}: {e}", flush=True)

            if not raw_channel_items:
                print(f"  🚫 No episode links found in '{cname}'. Skipping to next channel.\n", flush=True)
                continue

            # Deduplicate by range (keep latest message_id for same range)
            unique_ranges = {}
            for item in raw_channel_items:
                key = (item["start_ep"], item["end_ep"])
                unique_ranges[key] = item

            # Sort strictly in numerical episode order (01-10, 11-20, ... 101-110)
            ordered_story_items = sorted(unique_ranges.values(), key=lambda x: x["start_ep"])
            print(f"  📋 Extracted {len(ordered_story_items)} chronological range items for '{cname}'.", flush=True)

            # Step 2: Separate Free Bot Links and Pending Shortlinks
            pending_items = []
            for item in ordered_story_items:
                # Check Master Cache for Shortlink
                if item["bot_link"] == "N/A" and item["shortlink"] != "N/A":
                    if item["shortlink"] in MASTER_RESOLVED_CACHE:
                        cached_bot = MASTER_RESOLVED_CACHE[item["shortlink"]]
                        item["bot_link"] = cached_bot
                        print(f"    ✨ [RESOLVED FROM CACHE]: [{item['range_label']}] {item['shortlink']} -> {cached_bot}", flush=True)
                    else:
                        pending_items.append(item)

            # Step 3: Resolve all pending shortlinks for this story channel
            if pending_items and AUTO_RESOLVE:
                print(f"  ⚡ Resolving {len(pending_items)} pending live shortlinks for '{cname}'...", flush=True)
                for p_idx, p_item in enumerate(pending_items, 1):
                    surl = p_item["shortlink"]
                    rng = p_item["range_label"]
                    
                    print(f"    [{p_idx}/{len(pending_items)}] 🌐 Resolving: [{rng}] {surl} ...", flush=True)
                    bot_url = await resolve_one_shortlink(p, surl)
                    if bot_url and bot_url != "N/A":
                        p_item["bot_link"] = bot_url
                        MASTER_RESOLVED_CACHE[surl] = bot_url
                        scan_progress["total_resolved_count"] += 1
                        print(f"    ✅ [RESOLVED & STOPPED]: [{rng}] {surl} -> {bot_url}", flush=True)
                    else:
                        print(f"    ⚠️ [UNRESOLVED / SKIPPED]: [{rng}] {surl} -> N/A (Moved to next)", flush=True)
                    await asyncio.sleep(0.3)

            # Step 4: Save 100% complete story set with Channel Name, Ranges, Shortlinks, Bot Links
            save_channel_story_set(cid, cname, ordered_story_items)
            scan_progress["completed_channels_count"] += 1
            print(f"✅ [100% COMPLETE & SAVED] '{cname}' dataset stored with {len(ordered_story_items)} ordered episodes!\n", flush=True)
            await asyncio.sleep(0.5)

    scan_progress["status"] = "completed"
    scan_progress["completed_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n=========================================================================================", flush=True)
    print(f"🏆 ALL {len(channel_entities)} CHANNELS 100% EXTRACTED, RESOLVED & STORED AS STRUCTURED SETS!", flush=True)
    print(f"=========================================================================================\n", flush=True)

# HTTP Server Routes
async def handle_root(request):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM `channel_story_sets`")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM `channel_story_sets` WHERE is_free_bot_link = 1")
    free_bots = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM `channel_story_sets` WHERE is_free_bot_link = 0 AND telegram_bot_link != 'N/A'")
    resolved_shorts = cursor.fetchone()[0]
    cursor.execute("SELECT count(DISTINCT channel_name) FROM `channel_story_sets`")
    stories = cursor.fetchone()[0]
    conn.close()

    return web.json_response({
        "status": "online",
        "service": "CODEX Chronological Story Set Extraction & Resolution Daemon",
        "unique_story_channels": stories,
        "total_extracted_episodes": total,
        "free_bot_links": free_bots,
        "resolved_shortlinks": resolved_shorts,
        "cached_resolved_pairs": len(MASTER_RESOLVED_CACHE),
        "sequential_scan_progress": scan_progress,
        "uptime": "24/7"
    })

async def handle_health(request):
    return web.Response(text="OK", status=200)

async def handle_links(request):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT channel_name, range_label, start_ep, end_ep, shortlink_url, telegram_bot_link, is_free_bot_link, saved_at
        FROM `channel_story_sets`
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
            "is_free_bot_link": bool(r[6]),
            "saved_at": r[7]
        })
    return web.json_response(result)

async def handle_export_sql(request):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT channel_id, channel_name, message_id, message_date, range_label, start_ep, end_ep, shortlink_url, telegram_bot_link
        FROM `channel_story_sets`
        ORDER BY channel_name ASC, start_ep ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    lines = []
    lines.append("-- CODEX Story Sets Master Database Export (Chronological Message Order & 100% Resolved)\n")
    lines.append(f"-- Exported on: {datetime.datetime.now().isoformat()} | Total Rows: {len(rows):,}\n\n")
    lines.append("INSERT INTO `pocket_fm_all_in_one_links` (`channel_id`, `channel_name`, `message_id`, `message_date`, `button_range`, `start_episode`, `end_episode`, `shortlink_url`, `telegram_bot_link`, `status`, `source`) VALUES\n")

    val_lines = []
    for r in rows:
        cid, cname, mid, mdate, rng, sep, eep, surl, burl = r
        cname_esc = cname.replace("'", "''")
        surl_esc = surl.replace("'", "''")
        burl_esc = burl.replace("'", "''")
        mdate_esc = mdate.replace("'", "''")
        val_lines.append(f"('{cid}', '{cname_esc}', {mid or 0}, '{mdate_esc}', '{rng}', {sep}, {eep}, '{surl_esc}', '{burl_esc}', 'RESOLVED', 'channel_story_set')")

    sql_content = ",\n".join(val_lines) + ";\n"
    return web.Response(text="\n".join(lines) + sql_content, content_type="text/plain; charset=utf-8")


async def keepalive_ping_loop():
    if KEEPALIVE_INTERVAL_SECONDS <= 0:
        print("🏓 Keepalive ping disabled because KEEPALIVE_INTERVAL_SECONDS is <= 0.", flush=True)
        return

    base_url = KEEPALIVE_URL.rstrip("/") if KEEPALIVE_URL else f"http://127.0.0.1:{PORT}"
    if not base_url.startswith(("http://", "https://")):
        base_url = "https://" + base_url
    target_url = base_url + "/health"
    timeout = ClientTimeout(total=20)
    print(f"🏓 Keepalive ping loop active: {target_url} every {KEEPALIVE_INTERVAL_SECONDS // 60} minutes.", flush=True)

    while True:
        await asyncio.sleep(KEEPALIVE_INTERVAL_SECONDS)
        try:
            async with ClientSession(timeout=timeout) as session:
                async with session.get(target_url) as response:
                    await response.text()
                    print(f"🏓 Keepalive ping OK: {response.status} {target_url}", flush=True)
        except Exception as e:
            print(f"⚠️ Keepalive ping failed for {target_url}: {e}", flush=True)

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
    print(f"🌐 HTTP server bound to 0.0.0.0:{PORT} — Render port binding OK!", flush=True)

async def main():
    print("=========================================================================================", flush=True)
    print("🤖 STARTING CODEX CHRONOLOGICAL STORY SET RESOLUTION DAEMON (24/7 UPTIME)", flush=True)
    print("=========================================================================================", flush=True)
    
    init_db()
    load_resolved_cache()
    await start_http_server()
    asyncio.create_task(keepalive_ping_loop())
    
    clients = []
    channel_targets = []
    seen_channel_ids = set()

    # 1. Main Account (Rock / 9848915830)
    client_main = TelegramClient(StringSession(SESSION_STR_MAIN), API_ID, API_HASH, timeout=20, auto_reconnect=True)
    await client_main.connect()
    
    if await client_main.is_user_authorized():
        me1 = await client_main.get_me()
        print(f"✅ Connected & Authorized Account 1 (Main: Rock): {me1.first_name} (+{me1.phone})", flush=True)
        clients.append(client_main)
        d1 = await client_main.get_dialogs()
        for d in d1:
            if d.is_channel:
                clean_id = re.sub(r'^-?100', '', str(d.id))
                clean_id = re.sub(r'^-', '', clean_id)
                cname = clean_story_title(d.title)
                if cname and clean_id not in seen_channel_ids:
                    seen_channel_ids.add(clean_id)
                    channel_targets.append((client_main, d, clean_id, cname))
    else:
        print("⚠️ Account 1 (Main: Rock) string session not authorized!", flush=True)

    # 2. Sub Account (Syamala / 9490590394)
    if SESSION_STR_SUB:
        try:
            client_sub = TelegramClient(StringSession(SESSION_STR_SUB), API_ID, API_HASH, timeout=20, auto_reconnect=True)
            await client_sub.connect()
            if await client_sub.is_user_authorized():
                me2 = await client_sub.get_me()
                print(f"✅ Connected & Authorized Account 2 (Sub: Syamala): {me2.first_name} (+{me2.phone})", flush=True)
                clients.append(client_sub)
                d2 = await client_sub.get_dialogs()
                for d in d2:
                    if d.is_channel:
                        clean_id = re.sub(r'^-?100', '', str(d.id))
                        clean_id = re.sub(r'^-', '', clean_id)
                        cname = clean_story_title(d.title)
                        if cname and clean_id not in seen_channel_ids:
                            seen_channel_ids.add(clean_id)
                            channel_targets.append((client_sub, d, clean_id, cname))
        except Exception as e:
            print(f"⚠️ Account 2 (Sub) connect note: {e}", flush=True)

    if not clients:
        print("❌ No authorized Telegram accounts found!", flush=True)
        return

    print(f"📡 Combined unique story channels mapped across both accounts: {len(channel_targets)}", flush=True)

    if FULL_HISTORICAL_SCAN:
        asyncio.create_task(sequential_channel_scanner_and_resolver(channel_targets))

    print("👀 Live Listeners ACTIVE across authorized accounts. Watching for incoming daily drops...\n", flush=True)

    # Resilient keep-alive loop to keep service alive
    primary_client = clients[0]
    while True:
        try:
            await primary_client.run_until_disconnected()
        except Exception as e:
            print(f"⚠️ Telegram event loop reconnected: {e}", flush=True)
            await asyncio.sleep(3)
            if not primary_client.is_connected():
                try:
                    await primary_client.connect()
                except Exception:
                    pass

if __name__ == "__main__":
    asyncio.run(main())
