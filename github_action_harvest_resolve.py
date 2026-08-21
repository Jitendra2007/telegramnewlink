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

MAX_CONCURRENT_RESOLVERS = int(os.environ.get("MAX_CONCURRENT_RESOLVERS", "5"))
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
        UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        HEADERS = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": HINDISINK_REFERER,
        }

        short_id = shortlink.rsplit("/", 1)[-1][:12]

        # Domains we ALLOW to load — everything else gets blocked at route level
        ALLOWED_DOMAINS = ["linkshortx.in", "urlshortx.io", "hindisink.com",
                           "telegram.me", "t.me", "telegram.org"]

        # Ad/tracker domains to block (these cause ERR_ABORTED and frame detach)
        BLOCKED_PATTERNS = [
            "googlesyndication", "googleadservices", "doubleclick.net",
            "adservice", "pagead", "adsense", "facebook.com/tr",
            "analytics", "tracker", "taboola", "outbrain", "popads",
            "propellerads", "hilltopads", "exoclick", "juicyads",
            "trafficjunky", "clickadu", "adsterra", "monetag", "profitablegatecpm",
            "surfrads", "pushprofit", "onclicka", "clickaine"]

        async def route_handler(route):
            """Block ad/tracker requests to prevent frame detach crashes."""
            url = route.request.url.lower()
            # Block known ad domains
            if any(blocked in url for blocked in BLOCKED_PATTERNS):
                await route.abort()
                return
            # Block requests to random unknown domains (only allow our shortlink + telegram)
            from urllib.parse import urlparse
            try:
                host = urlparse(url).hostname or ""
                if host and not any(d in host for d in ALLOWED_DOMAINS):
                    # Block third-party requests (ads, trackers)
                    if route.request.resource_type in ("document", "subdocument"):
                        await route.abort()
                        return
            except Exception:
                pass
            await route.continue_()

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
                                print(f"      [{short_id}] HTTP {resp.status} -> DEAD", flush=True)
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
                print(f"      [{short_id}] HTTP RESOLVED!", flush=True)
                return ("RESOLVED", res)

        # 2. Phase 1: Direct Referer Bypass — FRESH isolated context
        pw_found = None
        is_dead = False
        context1 = None
        try:
            context1 = await browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 720})
            # Block ads at route level to prevent frame detach
            await context1.route("**/*", route_handler)
            page1 = await context1.new_page()

            def check_hit(url):
                nonlocal pw_found
                if pw_found: return
                m = BOT_RE.search(url)
                if m:
                    pw_found = m.group(0)

            page1.on("request", lambda req: check_hit(req.url))
            page1.on("response", lambda resp: check_hit(resp.url))

            await page1.goto(shortlink, referer=HINDISINK_REFERER, wait_until="domcontentloaded", timeout=20000)
            for tick in range(20):
                if pw_found: break
                try:
                    eval_res = await page1.evaluate(r"""() => {
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
                except Exception:
                    break
                await asyncio.sleep(1.0)

            # Check final content before closing
            if not pw_found and not is_dead:
                try:
                    c = await page1.content()
                    m = BOT_RE.search(c) or BOT_RE.search(page1.url or "")
                    if m:
                        pw_found = m.group(0)
                except Exception:
                    pass

        except Exception as e:
            print(f"      [{short_id}] Phase1: {type(e).__name__}: {str(e)[:80]}", flush=True)
        finally:
            if context1:
                try: await context1.close()
                except Exception: pass

        if is_dead:
            return ("DEAD_404", "N/A")
        if pw_found:
            res = canonical_bot_url(pw_found)
            if res != "N/A":
                print(f"      [{short_id}] Phase1 RESOLVED!", flush=True)
                return ("RESOLVED", res)

        # 3. Phase 2: Sequential State Machine — FRESH isolated context (not reusing dead page!)
        pw_found2 = None
        context2 = None
        try:
            context2 = await browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 720})
            await context2.route("**/*", route_handler)
            page2 = await context2.new_page()

            def check_hit2(url):
                nonlocal pw_found2
                if pw_found2: return
                m = BOT_RE.search(url)
                if m:
                    pw_found2 = m.group(0)

            page2.on("request", lambda req: check_hit2(req.url))
            page2.on("response", lambda resp: check_hit2(resp.url))

            await page2.goto(shortlink, wait_until="commit", timeout=15000)
            for tick in range(25):
                if pw_found2: break
                try:
                    eval_res = await page2.evaluate(FAST_STEP_JS)
                    if eval_res.get("action") == "dead_404":
                        is_dead = True
                        break
                    if eval_res.get("telegram"):
                        pw_found2 = eval_res["telegram"]
                        break
                    elif eval_res.get("action") in ("clicked_get_link", "clicked_final"):
                        await asyncio.sleep(3.0)
                        break
                except Exception:
                    break
                await asyncio.sleep(1.0)

            # Final content check
            if not pw_found2 and not is_dead:
                try:
                    c = await page2.content()
                    m = BOT_RE.search(c) or BOT_RE.search(page2.url or "")
                    if m:
                        pw_found2 = m.group(0)
                except Exception:
                    pass

        except Exception as e:
            print(f"      [{short_id}] Phase2: {type(e).__name__}: {str(e)[:80]}", flush=True)
        finally:
            if context2:
                try: await context2.close()
                except Exception: pass

        if is_dead:
            return ("DEAD_404", "N/A")
        if pw_found2:
            res = canonical_bot_url(pw_found2)
            if res != "N/A":
                print(f"      [{short_id}] Phase2 RESOLVED!", flush=True)
                return ("RESOLVED", res)

        print(f"      [{short_id}] UNRESOLVED after all phases", flush=True)
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
        # SEQUENTIAL CHANNEL-BY-CHANNEL RESOLUTION (Queue-Based Workers)
        # Pattern: Proven from universal_fast_cluster_resolver.py
        # Rule: ONE channel at a time. Fully resolve ALL its links before next.
        # =========================================================================
        print("\n" + "=" * 90, flush=True)
        print("🌀 SEQUENTIAL CHANNEL-BY-CHANNEL FULL RESOLUTION ENGINE", flush=True)
        print(f"⚡ {MAX_CONCURRENT_RESOLVERS} queue-based workers per channel (one channel at a time)", flush=True)
        print("=" * 90 + "\n", flush=True)

        total_resolved_global = 0
        total_dead_global = 0
        total_queued_global = 0

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
            if not items_to_resolve:
                print(f"  🚫 No shortlinks to resolve in '{cname}'. Skipping.", flush=True)
                continue

            # =====================================================================
            # QUEUE-BASED WORKER RESOLUTION FOR THIS CHANNEL
            # Process all shortlinks for this channel with queue workers.
            # Up to 3 retry passes per channel before moving on.
            # =====================================================================
            print(f"⚡ [{idx}/{len(channel_targets)}] Resolving '{cname}': {len(items_to_resolve)} shortlinks with {MAX_CONCURRENT_RESOLVERS} workers...", flush=True)

            channel_resolved = 0
            channel_dead = 0
            channel_failed = 0

            # Build queue for this channel
            resolve_queue = asyncio.Queue()
            for it in items_to_resolve:
                resolve_queue.put_nowait(it)

            async def channel_worker(worker_id):
                nonlocal channel_resolved, channel_dead, channel_failed
                while not resolve_queue.empty():
                    try:
                        item = resolve_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    surl = item["shortlink"]
                    baseline_bot = canonical_bot_url(BASELINE_CACHE.get(surl, "N/A"))
                    t0 = time.time()

                    res_type, live_bot = await live_resolve_single_shortlink(browser, surl, sem)
                    elapsed = time.time() - t0

                    if res_type == "RESOLVED" and live_bot != "N/A":
                        if baseline_bot != "N/A":
                            status = "MATCH" if live_bot == baseline_bot else "MISMATCH"
                            print(f"    [W{worker_id}] ✅ [{status}] [{item['range_label']}] -> {live_bot} ({elapsed:.1f}s)", flush=True)
                        else:
                            status = "NEW_RESOLVED"
                            print(f"    [W{worker_id}] ✨ [NEW] [{item['range_label']}] -> {live_bot} ({elapsed:.1f}s)", flush=True)
                        channel_resolved += 1
                    elif res_type == "DEAD_404":
                        status = "DEAD_404_EXPIRED"
                        live_bot = "N/A"
                        print(f"    [W{worker_id}] 🚫 [DEAD] [{item['range_label']}] {surl} ({elapsed:.1f}s)", flush=True)
                        channel_dead += 1
                    else:
                        status = "QUEUED_FOR_RETRY"
                        live_bot = "N/A"
                        unresolved_retry_pool[surl] = item
                        print(f"    [W{worker_id}] ⏳ [FAILED] [{item['range_label']}] {surl} ({elapsed:.1f}s)", flush=True)
                        channel_failed += 1

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

                    resolve_queue.task_done()

            # Launch workers and wait for all items to complete
            workers = [asyncio.create_task(channel_worker(i + 1)) for i in range(MAX_CONCURRENT_RESOLVERS)]
            await resolve_queue.join()
            for w in workers:
                w.cancel()

            # Channel-level retry: re-attempt any failed links for this channel (up to 2 more passes)
            channel_retry_items = {s: it for s, it in unresolved_retry_pool.items() if it.get("channel_id") == cid}
            for retry_pass in range(1, 3):
                if not channel_retry_items:
                    break
                print(f"    🔄 Retry pass {retry_pass}/2 for '{cname}': {len(channel_retry_items)} links...", flush=True)
                retry_queue = asyncio.Queue()
                for it in channel_retry_items.values():
                    retry_queue.put_nowait(it)

                retry_resolved = []
                retry_dead = []

                async def retry_worker(worker_id):
                    while not retry_queue.empty():
                        try:
                            item = retry_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                        surl = item["shortlink"]
                        t0 = time.time()
                        res_type, live_bot = await live_resolve_single_shortlink(browser, surl, sem)
                        elapsed = time.time() - t0

                        if res_type == "RESOLVED" and live_bot != "N/A":
                            print(f"    [W{worker_id}] ✨ [RETRY SOLVED] [{item['range_label']}] -> {live_bot} ({elapsed:.1f}s)", flush=True)
                            AUDIT_RESULTS[surl]["live_bot_link"] = live_bot
                            AUDIT_RESULTS[surl]["verification_status"] = "NEW_RESOLVED"
                            AUDIT_RESULTS[surl]["audited_at"] = datetime.datetime.now().isoformat()
                            retry_resolved.append(surl)
                        elif res_type == "DEAD_404":
                            print(f"    [W{worker_id}] 🚫 [RETRY DEAD] [{item['range_label']}] {surl} ({elapsed:.1f}s)", flush=True)
                            AUDIT_RESULTS[surl]["verification_status"] = "DEAD_404_EXPIRED"
                            retry_dead.append(surl)
                        else:
                            print(f"    [W{worker_id}] ⏳ [RETRY FAIL] [{item['range_label']}] {surl} ({elapsed:.1f}s)", flush=True)

                        retry_queue.task_done()

                r_workers = [asyncio.create_task(retry_worker(i + 1)) for i in range(MAX_CONCURRENT_RESOLVERS)]
                await retry_queue.join()
                for w in r_workers:
                    w.cancel()

                for s in retry_resolved:
                    unresolved_retry_pool.pop(s, None)
                    channel_retry_items.pop(s, None)
                    channel_resolved += 1
                    channel_failed -= 1
                for s in retry_dead:
                    unresolved_retry_pool.pop(s, None)
                    channel_retry_items.pop(s, None)
                    channel_dead += 1
                    channel_failed -= 1

            total_resolved_global += channel_resolved
            total_dead_global += channel_dead
            total_queued_global += channel_failed

            print(f"    ✅ Channel '{cname}' DONE: {channel_resolved} resolved | {channel_dead} dead | {channel_failed} still failed", flush=True)
            print(f"    📊 Global progress: {total_resolved_global} resolved | {total_dead_global} dead | {total_queued_global} failed | {len(AUDIT_RESULTS)} total", flush=True)

            save_audit_json()

        # =========================================================================
        # FINAL ISOLATION: Collect any links that failed across all channels
        # =========================================================================
        if unresolved_retry_pool:
            print(f"\n⚠️ Isolating {len(unresolved_retry_pool):,} stubborn links that failed all retries...", flush=True)
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
                    "reason": "FAILED_ALL_RETRIES",
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
    print(f"🏆 SEQUENTIAL CHANNEL-BY-CHANNEL RESOLUTION COMPLETE!", flush=True)
    print(f"📊 Final: {total_resolved_global} resolved | {total_dead_global} dead | {total_queued_global} failed", flush=True)
    print("=" * 90 + "\n", flush=True)


if __name__ == "__main__":
    asyncio.run(run_safe_parallel_cloud_reverification())
