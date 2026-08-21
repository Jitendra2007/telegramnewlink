#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CODEX Master Cloud 5-Cycle Multi-Pass Safe Harvester & Link Resolver
Runs on GitHub Actions with 7 GB RAM.
Features:
  - 15 Parallel Async Browser Contexts
  - 5-Cycle Retry Engine: Re-attempts all failed/unresolved links in 5 successive passes
  - If still unresolved after 5 full cycles, isolates them into `stubborn_failed_links_for_review.json` & `.md`
  - Zero disruption to baseline cache
  - Outputs:
      * cloud_reverified_audit.json
      * cloud_reverified_audit.sql
      * cloud_verification_discrepancy_report.md
      * stubborn_failed_links_for_review.json
      * stubborn_failed_links_for_review.md
"""

import asyncio
import datetime
import json
import os
import re
import sys
import time
from urllib.parse import urlparse
from aiohttp import ClientSession, ClientTimeout
from telethon import TelegramClient
from telethon.sessions import StringSession
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding='utf-8')

API_ID = int(os.environ.get("API_ID", "36198115"))
API_HASH = os.environ.get("API_HASH", "ce040e05f933e3e0a811f186c3d5d3bb")
SESSION_STR_MAIN = os.environ.get("TELEGRAM_STRING_SESSION", "")
SESSION_STR_SUB = os.environ.get("TELEGRAM_STRING_SESSION_SUB", "")

MAX_CONCURRENT_RESOLVERS = int(os.environ.get("MAX_CONCURRENT_RESOLVERS", "15"))
MAX_RETRY_CYCLES = int(os.environ.get("MAX_RETRY_CYCLES", "5"))

BASE_CACHE_PATH = "master_resolved_cache.json"
SKIPPED_CHANNELS_PATH = "skipped_channels_no_shortlinks.json"

AUDIT_JSON_PATH = "cloud_reverified_audit.json"
AUDIT_SQL_PATH = "cloud_reverified_audit.sql"
AUDIT_REPORT_MD = "cloud_verification_discrepancy_report.md"

STUBBORN_JSON_PATH = "stubborn_failed_links_for_review.json"
STUBBORN_REPORT_MD = "stubborn_failed_links_for_review.md"

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

BASELINE_CACHE = {}
SKIPPED_CHANNELS_REGISTRY = {}
AUDIT_RESULTS = {}
STUBBORN_FAILED_REGISTRY = {}


def canonical_bot_url(url):
    if not url or url == "N/A":
        return "N/A"
    m = BOT_RE.search(url)
    if m:
        bot_name = m.group(1)
        payload = m.group(2)
        return f"https://t.me/{bot_name}?start={payload}"
    return "N/A"


def load_baseline():
    global BASELINE_CACHE, SKIPPED_CHANNELS_REGISTRY, AUDIT_RESULTS, STUBBORN_FAILED_REGISTRY
    if os.path.exists(BASE_CACHE_PATH):
        try:
            with open(BASE_CACHE_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
                BASELINE_CACHE = {k: canonical_bot_url(v) for k, v in raw.items()}
            print(f"📦 Loaded {len(BASELINE_CACHE):,} baseline cached pairs for comparison.", flush=True)
        except Exception as e:
            print(f"⚠️ Error loading baseline cache: {e}", flush=True)

    if os.path.exists(SKIPPED_CHANNELS_PATH):
        try:
            with open(SKIPPED_CHANNELS_PATH, "r", encoding="utf-8") as f:
                SKIPPED_CHANNELS_REGISTRY = json.load(f)
            print(f"🚫 Loaded {len(SKIPPED_CHANNELS_REGISTRY):,} skipped channels registry.", flush=True)
        except Exception as e:
            print(f"⚠️ Error loading skip registry: {e}", flush=True)


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

    if os.path.exists(AUDIT_JSON_PATH):
        try:
            with open(AUDIT_JSON_PATH, "r", encoding="utf-8") as f:
                AUDIT_RESULTS = json.load(f)
            print(f"📋 Loaded {len(AUDIT_RESULTS):,} previously audited links.", flush=True)
        except Exception:
            AUDIT_RESULTS = {}

    if os.path.exists(STUBBORN_JSON_PATH):
        try:
            with open(STUBBORN_JSON_PATH, "r", encoding="utf-8") as f:
                STUBBORN_FAILED_REGISTRY = json.load(f)
            print(f"⚠️ Loaded {len(STUBBORN_FAILED_REGISTRY):,} persistent stubborn failed links.", flush=True)
        except Exception:
            STUBBORN_FAILED_REGISTRY = {}


def save_audit_json():
    try:
        with open(AUDIT_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(AUDIT_RESULTS, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Error saving audit JSON: {e}", flush=True)


def save_stubborn_json_and_report():
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    try:
        with open(STUBBORN_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(STUBBORN_FAILED_REGISTRY, f, ensure_ascii=False, indent=2)
        print(f"💾 Stubborn Failed Links JSON updated: {len(STUBBORN_FAILED_REGISTRY):,} links in {STUBBORN_JSON_PATH}", flush=True)
    except Exception as e:
        print(f"⚠️ Error saving stubborn JSON: {e}", flush=True)

    try:
        with open(STUBBORN_REPORT_MD, "w", encoding="utf-8") as f:
            f.write(f"# ⚠️ Stubborn Failed Shortlinks Review Report (Failed 5 Consecutive Cycles)\n\n")
            f.write(f"**Generated:** `{now_str}` | **Total Stubborn Links:** `{len(STUBBORN_FAILED_REGISTRY):,}`\n\n")
            f.write(f"> These links were attempted across 5 complete separate browser cycles with fresh contexts and still failed to resolve or returned provider 404 errors. They are isolated here for manual inspection.\n\n")
            f.write(f"| # | Story Channel | Episode Range | Shortlink | Reason / Error |\n")
            f.write(f"| :--- | :--- | :--- | :--- | :--- |\n")
            for idx, (surl, info) in enumerate(STUBBORN_FAILED_REGISTRY.items(), 1):
                cname = info.get("channel_name", "")
                rng = info.get("range_label", "")
                reason = info.get("reason", "UNRESOLVED_AFTER_5_CYCLES")
                f.write(f"| {idx} | {cname} | {rng} | `{surl}` | `{reason}` |\n")
            f.write("\n")
        print(f"📄 Stubborn Failed Links Review Report generated: {STUBBORN_REPORT_MD}", flush=True)
    except Exception as e:
        print(f"⚠️ Error saving stubborn MD report: {e}", flush=True)


def generate_audit_sql_and_report():
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    matches = 0
    new_resolved = 0
    dead_404 = 0
    mismatches = []
    unresolved = []

    sql_lines = [
        f"-- =========================================================================\n",
        f"-- CODEX MASTER AUDITED DATASET (STANDARD pocket_fm_bot_links FORMAT)\n",
        f"-- Generated at: {now_str} | Total Links Audited: {len(AUDIT_RESULTS):,}\n",
        f"-- =========================================================================\n\n",
        "INSERT INTO `pocket_fm_bot_links` (`telegram_channel_id`, `telegram_channel_name`, `invite_link`, `message_id`, `button_range`, `shortlink_url`, `bot_link_url`, `status`) VALUES\n"
    ]
    
    val_lines = []
    for surl, data in AUDIT_RESULTS.items():
        vstat = data.get("verification_status", "UNKNOWN")
        live_bot = canonical_bot_url(data.get("live_bot_link", "N/A"))
        cname = data.get("channel_name", "").replace("'", "''")
        cid = data.get("channel_id", "")
        rng = data.get("range_label", "")
        mid = data.get("message_id", 0)
        
        if vstat in ("MATCH", "CACHE_VERIFIED"):
            matches += 1
        elif vstat == "NEW_RESOLVED":
            new_resolved += 1
        elif vstat == "DEAD_404_EXPIRED":
            dead_404 += 1
        elif vstat == "MISMATCH":
            mismatches.append(data)
        elif vstat == "FAILED_TO_RESOLVE":
            unresolved.append(data)

        if live_bot != "N/A":
            surl_esc = surl.replace("'", "''")
            burl_esc = live_bot.replace("'", "''")
            val_lines.append(f"('{cid}', '{cname}', '', {mid}, '{rng}', '{surl_esc}', '{burl_esc}', 'RESOLVED')")
        elif vstat != "DEAD_404_EXPIRED":
            surl_esc = surl.replace("'", "''")
            val_lines.append(f"('{cid}', '{cname}', '', {mid}, '{rng}', '{surl_esc}', 'N/A', 'PENDING')")

    if val_lines:
        sql_lines.append(",\n".join(val_lines) + ";\n")
        with open(AUDIT_SQL_PATH, "w", encoding="utf-8") as f:
            f.writelines(sql_lines)
        print(f"💾 Clean Audit SQL Dump generated: {len(val_lines):,} rows in {AUDIT_SQL_PATH}", flush=True)

    with open(AUDIT_REPORT_MD, "w", encoding="utf-8") as f:
        f.write(f"# 🛡️ CODEX Cloud Re-Verification & Discrepancy Audit Report\n\n")
        f.write(f"**Generated:** `{now_str}`\n\n")
        f.write(f"### 📊 Summary Statistics\n")
        f.write(f"- **Total Shortlinks Audited**: `{len(AUDIT_RESULTS):,}`\n")
        f.write(f"- ✅ **100% Exact Matches (Active Verified)**: `{matches:,}`\n")
        f.write(f"- ✨ **Newly Resolved Links (Previously Pending)**: `{new_resolved:,}`\n")
        f.write(f"- 🚫 **Dead/Expired 404 Links on Provider**: `{dead_404:,}`\n")
        f.write(f"- ⚠️ **True Discrepancies / Mismatches**: `{len(mismatches):,}`\n")
        f.write(f"- ❌ **Permanently Unresolved Links (Failed 5 Cycles)**: `{len(unresolved):,}`\n\n")

        if mismatches:
            f.write(f"### ⚠️ Discrepancy / Mismatch Review List\n")
            f.write(f"| Story Channel | Range | Shortlink | Baseline Bot Link | Live Resolved Bot Link |\n")
            f.write(f"| :--- | :--- | :--- | :--- | :--- |\n")
            for m in mismatches[:100]:
                f.write(f"| {m.get('channel_name')} | {m.get('range_label')} | `{m.get('shortlink')}` | `{m.get('baseline_bot_link')}` | `{m.get('live_bot_link')}` |\n")
            f.write("\n")

        if dead_404:
            f.write(f"### 🚫 Dead/Expired 404 Links (Deleted by Shortlink Provider)\n")
            f.write(f"| Story Channel | Range | Shortlink | Status |\n")
            f.write(f"| :--- | :--- | :--- | :--- |\n")
            for surl, data in list(AUDIT_RESULTS.items())[:100]:
                if data.get("verification_status") == "DEAD_404_EXPIRED":
                    f.write(f"| {data.get('channel_name')} | {data.get('range_label')} | `{surl}` | 404 Not Found / Expired |\n")
            f.write("\n")

    print(f"📄 Human Verification Report generated: {AUDIT_REPORT_MD}", flush=True)


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
        raw_url = m.group(0).strip()
        parsed = urlparse(raw_url)
        domain = parsed.netloc.lower()
        scheme = parsed.scheme.lower() or "https"
        # Strip markdown formatting artifacts, asterisks, trailing underscores, and brackets
        path = parsed.path.rstrip('_*)]>.,/~ ')
        if not path or path == "/":
            return "N/A"
        if INVALID_SLUGS_RE.search(path):
            return "N/A"
        # Exact slug case preserved, domain normalized
        clean_url = f"{scheme}://{domain}{path}"
        return clean_url
    return "N/A"


FAST_STEP_JS = r"""
async () => {
  const BOT_PAT = /(?:https?:\/\/)?(?:telegram\.me|t\.me)\/[A-Za-z0-9_]+\?start=[A-Za-z0-9_%+\/=\-]+/i;

  // 1. Scan for telegram bot link
  const bodyText = document.body ? document.body.innerText : "";
  const tgText = bodyText.match(BOT_PAT);
  if (tgText) return {action: "found_text", telegram: tgText[0]};

  for (const a of document.querySelectorAll("a")) {
    const href = a.href || "";
    if (BOT_PAT.test(href)) return {action: "found_anchor", telegram: href};
  }

  // 2. Check for 404 / Dead
  const title = (document.title || "").toLowerCase();
  const bLow = bodyText.toLowerCase();
  if (title.includes("404") || title.includes("not found") || bLow.includes("wrong turn") || bLow.includes("doesn't exist") || bLow.includes("may have expired") || bLow.includes("link expired") || bLow.includes("invalid key")) {
    return {action: "dead_404"};
  }

  // 3. Unhide hidden elements
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

  // 4. Submit form#fwd or form#rtg (Hindisink steps)
  const bypassForm = document.querySelector("form#fwd, form#rtg, form#landing");
  if (bypassForm) {
    try {
      HTMLFormElement.prototype.submit.call(bypassForm);
      return {action: "submitted_bypass_form"};
    } catch(e) {}
  }

  // 5. Final Get Link (.get-link)
  const getLink = document.querySelector(".get-link, #getlink, a.get-link");
  if (getLink) {
    const disabled = getLink.classList.contains("disabled") || getLink.getAttribute("aria-disabled") === "true" || (getLink.innerText||"").toLowerCase().includes("wait");
    if (!disabled) {
      try { getLink.click(); } catch(e) {}
      return {action: "clicked_get_link"};
    }
    return {action: "waiting_timer"};
  }

  // 6. Click #final / continue / start
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

  return {action: "nothing_matched"};
}
"""


async def live_resolve_single_shortlink(browser, shortlink, sem):
    async with sem:
        HEADERS = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": HINDISINK_REFERER,
        }

        # 1. Fast HTTP Redirect Check (0.5s)
        found = None
        current_url = shortlink
        try:
            async with ClientSession(timeout=ClientTimeout(total=5), headers=HEADERS) as session:
                for _ in range(6):
                    if not current_url or not current_url.startswith("http"):
                        break
                    m = BOT_RE.search(current_url)
                    if m:
                        found = m.group(0)
                        break
                    try:
                        async with session.get(current_url, allow_redirects=False, ssl=False, timeout=ClientTimeout(total=4)) as resp:
                            if resp.status in (404, 410):
                                return ("DEAD_404", "N/A")
                            loc = resp.headers.get("Location", "")
                            if loc:
                                m = BOT_RE.search(loc)
                                if m:
                                    found = m.group(0)
                                    break
                                current_url = loc if loc.startswith("http") else __import__("urllib.parse", fromlist=["urljoin"]).urljoin(current_url, loc)
                                continue
                            body = await resp.text(encoding="utf-8", errors="ignore")
                            if any(w in body.lower() for w in ["404 not found", "wrong turn", "doesn't exist", "may have expired"]):
                                return ("DEAD_404", "N/A")
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
            res = canonical_bot_url(found)
            if res != "N/A":
                return ("RESOLVED", res)

        # 2. Playwright Chromium with Popup Auto-Close & State Machine
        pw_found = None
        is_dead = False
        context = None
        try:
            context = await browser.new_context(
                user_agent=HEADERS["User-Agent"],
                viewport={"width": 1280, "height": 720},
                java_script_enabled=True,
            )
            
            async def on_popup(pop):
                try:
                    p_url = pop.url or ""
                    if not any(h in p_url for h in ["linkshortx", "urlshortx", "hindisink", "telegram", "t.me"]):
                        await pop.close()
                except Exception:
                    pass
            context.on("page", lambda p: asyncio.create_task(on_popup(p)))

            page = await context.new_page()

            def check_hit(url):
                nonlocal pw_found
                if pw_found: return
                m = BOT_RE.search(url)
                if m:
                    pw_found = m.group(0)

            page.on("request", lambda req: check_hit(req.url))
            page.on("response", lambda resp: check_hit(resp.url))

            # Phase 1: Fast Direct Referer Loophole (Natural 10-12s Wait)
            try:
                await page.goto(shortlink, referer=HINDISINK_REFERER, wait_until="domcontentloaded", timeout=18000)
                for _ in range(20):
                    if pw_found: break
                    eval_res = await page.evaluate(r"""() => {
                        const body = (document.body ? document.body.innerText : "").toLowerCase();
                        if (body.includes("404 not found") || body.includes("wrong turn") || body.includes("doesn't exist") || body.includes("may have expired")) {
                            return {action: "dead_404"};
                        }
                        const gl = document.querySelector(".get-link, #getlink, a.get-link");
                        if (!gl) return {action: "waiting"};
                        const locked = gl.classList.contains("disabled") || gl.getAttribute("aria-disabled") === "true" || (gl.innerText||'').toLowerCase().includes("wait");
                        if (!locked) {
                            try { gl.click(); } catch(e){}
                            return {action: "clicked_get_link"};
                        }
                        return {action: "waiting_timer"};
                    }""")
                    act = eval_res.get("action", "")
                    if act == "dead_404":
                        is_dead = True
                        break
                    elif act == "clicked_get_link":
                        await asyncio.sleep(3.0)
                        break
                    await asyncio.sleep(1.0)
            except Exception:
                pass

            if is_dead:
                return ("DEAD_404", "N/A")

            # Phase 2: Sequential State Machine Fallback if Phase 1 didn't catch it
            if not pw_found:
                try:
                    await page.goto(shortlink, wait_until="commit", timeout=15000)
                    for _ in range(25):
                        if pw_found: break
                        eval_res = await page.evaluate(FAST_STEP_JS)
                        if eval_res.get("action") == "dead_404":
                            is_dead = True
                            break
                        if eval_res.get("telegram"):
                            pw_found = eval_res["telegram"]
                            break
                        elif eval_res.get("action") in ("clicked_get_link", "clicked_final"):
                            await asyncio.sleep(3.0)
                            break
                        await asyncio.sleep(1.0)
                except Exception:
                    pass

            if is_dead:
                return ("DEAD_404", "N/A")

            if not pw_found:
                try:
                    c = await page.content()
                    m = BOT_RE.search(c) or BOT_RE.search(page.url or "")
                    if m:
                        pw_found = m.group(0)
                except Exception:
                    pass

        except Exception:
            pass
        finally:
            if context:
                try:
                    await context.close()
                except Exception:
                    pass

        if pw_found:
            return ("RESOLVED", canonical_bot_url(pw_found))
        if is_dead:
            return ("DEAD_404", "N/A")
        return ("UNRESOLVED", "N/A")


async def run_safe_parallel_cloud_reverification():
    print("=" * 90, flush=True)
    print(f"🚀 CODEX 5-CYCLE MULTI-PASS RE-VERIFICATION & AUDIT ENGINE (7GB RAM RUNNER)", flush=True)
    print(f"⏰ Execution Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}", flush=True)
    print(f"⚡ Max Concurrent Browser Resolvers: {MAX_CONCURRENT_RESOLVERS} | Max Retry Cycles: {MAX_RETRY_CYCLES}", flush=True)
    print("=" * 90, flush=True)

    load_baseline()

    clients = []
    channel_targets = []
    seen_channel_ids = set()

    # Connect Account 1 (Rock)
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

    # Connect Account 2 (Syamala)
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
        print("❌ No authorized Telegram accounts found!", flush=True)
        return

    print(f"📡 Found {len(channel_targets)} total channels across both accounts.", flush=True)

    sem = asyncio.Semaphore(MAX_CONCURRENT_RESOLVERS)
    all_harvested_items = []
    unresolved_retry_pool = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox", "--disable-setuid-sandbox",
                "--disable-dev-shm-usage", "--disable-gpu",
                "--disable-extensions", "--ignore-certificate-errors",
                "--disable-images", "--blink-settings=imagesEnabled=false",
            ]
        )

        # =========================================================================
        # CYCLE 1: Full Channel-by-Channel Scan & Initial Parallel Resolution
        # =========================================================================
        print("\n" + "=" * 90, flush=True)
        print("🌀 STARTING CYCLE 1/5: Full Channel-by-Channel Extraction & Audit", flush=True)
        print("=" * 90 + "\n", flush=True)

        for idx, (cli, d, cid, cname) in enumerate(channel_targets, 1):
            if cid in SKIPPED_CHANNELS_REGISTRY:
                continue

            print(f"📖 [{idx}/{len(channel_targets)}] Scanning: '{cname}' (ID: {cid})...", flush=True)
            raw_channel_items = []
            msg_count = 0
            scan_error = False
            try:
                async for message in cli.iter_messages(d.entity, reverse=True, limit=None):
                    msg_count += 1
                    mdate = message.date.isoformat() if message.date else ""
                    if message.reply_markup and hasattr(message.reply_markup, 'rows'):
                        for row in message.reply_markup.rows:
                            for btn in row.buttons:
                                if hasattr(btn, 'url') and btn.url:
                                    s_ep, e_ep, formatted_range = parse_range_numbers(getattr(btn, 'text', ''))
                                    if s_ep is not None:
                                        raw_channel_items.append({
                                            "channel_id": cid,
                                            "channel_name": cname,
                                            "message_id": message.id,
                                            "message_date": mdate,
                                            "start_ep": s_ep, "end_ep": e_ep,
                                            "range_label": formatted_range,
                                            "shortlink": normalize_shortlink(btn.url),
                                            "bot_link": canonical_bot_url(btn.url)
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
                                "channel_id": cid,
                                "channel_name": cname,
                                "message_id": message.id,
                                "message_date": mdate,
                                "start_ep": s_ep, "end_ep": e_ep,
                                "range_label": formatted_range,
                                "shortlink": normalize_shortlink(s_m.group(0)) if s_m else "N/A",
                                "bot_link": canonical_bot_url(b_m.group(0)) if b_m else "N/A"
                            })
            except Exception as e:
                scan_error = True
                print(f"⚠️ Error scanning channel {cname}: {e}", flush=True)

            if scan_error:
                continue

            if not raw_channel_items:
                print(f"  🚫 No episode links found in '{cname}' ({msg_count} msgs scanned). Skipping.", flush=True)
                save_skipped_channel(cid, cname, reason="no_links_found")
                continue

            has_any_shortlink = any(i["shortlink"] != "N/A" and i["shortlink"] for i in raw_channel_items)
            if not has_any_shortlink:
                print(f"  🚫 Only free bot links in '{cname}' (0 shortlinks). Skipping.", flush=True)
                save_skipped_channel(cid, cname, reason="only_free_bot_links")
                continue

            unique_ranges = {}
            for item in raw_channel_items:
                unique_ranges[(item["start_ep"], item["end_ep"])] = item
            ordered_story_items = sorted(unique_ranges.values(), key=lambda x: x["start_ep"])
            all_harvested_items.extend(ordered_story_items)

            items_to_resolve = [it for it in ordered_story_items if it.get("shortlink", "N/A") != "N/A"]
            print(f"⚡ [{idx}/{len(channel_targets)}] Auditing '{cname}' ({len(items_to_resolve)} links in parallel)...", flush=True)

            async def audit_worker_cycle1(item):
                surl = item["shortlink"]
                baseline_bot = canonical_bot_url(BASELINE_CACHE.get(surl, "N/A"))

                res_type, live_bot = await live_resolve_single_shortlink(browser, surl, sem)

                if res_type == "RESOLVED" and live_bot != "N/A":
                    if baseline_bot != "N/A":
                        status = "MATCH" if live_bot == baseline_bot else "MISMATCH"
                        print(f"    ✅ [{status}]: [{item['range_label']}] -> {live_bot}", flush=True)
                    else:
                        status = "NEW_RESOLVED"
                        print(f"    ✨ [NEW RESOLVED]: [{item['range_label']}] {surl} -> {live_bot}", flush=True)
                elif res_type == "DEAD_404":
                    status = "DEAD_404_EXPIRED"
                    live_bot = "N/A"
                    print(f"    🚫 [DEAD 404]: [{item['range_label']}] {surl}", flush=True)
                else:
                    status = "QUEUED_FOR_RETRY"
                    live_bot = "N/A"
                    unresolved_retry_pool[surl] = item
                    print(f"    ⏳ [QUEUED FOR RETRY]: [{item['range_label']}] {surl}", flush=True)

                AUDIT_RESULTS[surl] = {
                    "channel_id": item["channel_id"],
                    "channel_name": item["channel_name"],
                    "range_label": item["range_label"],
                    "start_ep": item["start_ep"],
                    "end_ep": item["end_ep"],
                    "shortlink": surl,
                    "baseline_bot_link": baseline_bot,
                    "live_bot_link": live_bot,
                    "verification_status": status,
                    "audited_at": datetime.datetime.now().isoformat()
                }

            await asyncio.gather(*(audit_worker_cycle1(item) for item in items_to_resolve))

            if idx % 5 == 0:
                save_audit_json()

        save_audit_json()
        print(f"\n✅ Cycle 1 Complete! Total links queued for retry: {len(unresolved_retry_pool):,}", flush=True)

        # =========================================================================
        # CYCLES 2 to 5: Targeted Multi-Pass Retry on Remaining Unresolved Links
        # =========================================================================
        for cycle in range(2, MAX_RETRY_CYCLES + 1):
            if not unresolved_retry_pool:
                print(f"\n🎉 ALL LINKS RESOLVED! No remaining unresolved links for Cycle {cycle}.", flush=True)
                break

            print("\n" + "=" * 90, flush=True)
            print(f"🔄 STARTING RETRY CYCLE {cycle}/{MAX_RETRY_CYCLES}: Re-attempting {len(unresolved_retry_pool):,} remaining failed links", flush=True)
            print("=" * 90 + "\n", flush=True)

            resolved_in_this_cycle = []
            dead_in_this_cycle = []

            async def retry_worker(surl, item):
                res_type, live_bot = await live_resolve_single_shortlink(browser, surl, sem)

                if res_type == "RESOLVED" and live_bot != "N/A":
                    print(f"    ✨ [RESOLVED ON CYCLE {cycle}]: [{item['range_label']}] {surl} -> {live_bot}", flush=True)
                    AUDIT_RESULTS[surl]["live_bot_link"] = live_bot
                    AUDIT_RESULTS[surl]["verification_status"] = "NEW_RESOLVED"
                    AUDIT_RESULTS[surl]["audited_at"] = datetime.datetime.now().isoformat()
                    resolved_in_this_cycle.append(surl)
                elif res_type == "DEAD_404":
                    print(f"    🚫 [CONFIRMED DEAD 404 ON CYCLE {cycle}]: [{item['range_label']}] {surl}", flush=True)
                    AUDIT_RESULTS[surl]["verification_status"] = "DEAD_404_EXPIRED"
                    dead_in_this_cycle.append(surl)
                else:
                    print(f"    ⏳ [STILL PENDING CYCLE {cycle}]: [{item['range_label']}] {surl}", flush=True)

            await asyncio.gather(*(retry_worker(surl, item) for surl, item in list(unresolved_retry_pool.items())))

            for s in resolved_in_this_cycle:
                unresolved_retry_pool.pop(s, None)
            for s in dead_in_this_cycle:
                unresolved_retry_pool.pop(s, None)

            save_audit_json()
            print(f"📊 Cycle {cycle} results: {len(resolved_in_this_cycle)} solved, {len(dead_in_this_cycle)} dead, {len(unresolved_retry_pool)} remaining.", flush=True)
            await asyncio.sleep(2.0)

        # =========================================================================
        # FINAL ISOLATION: Collect any links that failed all 5 cycles
        # =========================================================================
        if unresolved_retry_pool:
            print(f"\n⚠️ Isolating {len(unresolved_retry_pool):,} stubborn links that failed all 5 cycles...", flush=True)
            for surl, item in unresolved_retry_pool.items():
                if surl in AUDIT_RESULTS:
                    AUDIT_RESULTS[surl]["verification_status"] = "FAILED_TO_RESOLVE"
                STUBBORN_FAILED_REGISTRY[surl] = {
                    "channel_id": item["channel_id"],
                    "channel_name": item["channel_name"],
                    "range_label": item["range_label"],
                    "start_ep": item["start_ep"],
                    "end_ep": item["end_ep"],
                    "shortlink": surl,
                    "reason": "FAILED_5_CONSECUTIVE_CYCLES",
                    "isolated_at": datetime.datetime.now().isoformat()
                }

        await browser.close()

    # Final Saves & Reports
    save_audit_json()
    save_stubborn_json_and_report()
    generate_audit_sql_and_report()

    for cli in clients:
        try:
            await cli.disconnect()
        except Exception:
            pass

    print("\n" + "=" * 90, flush=True)
    print(f"🏆 COMPLETE 5-CYCLE AUDIT FINISHED! All reports & isolated files generated safely.", flush=True)
    print("=" * 90 + "\n", flush=True)


if __name__ == "__main__":
    asyncio.run(run_safe_parallel_cloud_reverification())
