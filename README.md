# 📡 Telegram Live Link Watcher Daemon (24/7 Cloud Service)

A 24/7 background Telegram userbot listener deployed to cloud hosting (Render / VPS) that continuously monitors all joined story channels on your account, extracts new live episode shortlinks and bot links, automatically consolidates 10-episode batches, and forwards new drops directly to your Telegram **Saved Messages**.

---

## 🌟 Key Features

1. **24/7 Cloud Operation**: Runs non-stop in the cloud with zero need for your local PC to be turned on.
2. **Dynamic 10-Episode Consolidation**:
   - Ingests daily sub-divided fragments (`901-904`, `905-907`, etc.).
   - Automatically marks fragments as `SUPERSEDED` when the complete 10-episode pack (`901-910`) is posted.
3. **Instant Telegram Forwarding**:
   - Sends every newly posted link directly to your personal **Saved Messages** on Telegram with clear status badges.
4. **Built-in HTTP Health & REST API**:
   - `GET /`: Service status and live link counts.
   - `GET /health`: Health-check endpoint for Render keep-alive.
   - `GET /links`: Returns all active harvested links as JSON.

---

## 🚀 Environment Variables

| Variable | Description |
| :--- | :--- |
| `API_ID` | Telegram App API ID (`36198115`) |
| `API_HASH` | Telegram App API Hash |
| `TELEGRAM_STRING_SESSION` | Authorized Telethon StringSession for the account |
| `PORT` | HTTP Web server port (`8080`) |
| `FORWARD_TO_SAVED_MESSAGES` | Set `true` to forward new drops to Telegram Saved Messages |
| `KEEPALIVE_INTERVAL_SECONDS` | Seconds between automatic health pings; defaults to `780` (13 minutes). Set `0` to disable. |
| `KEEPALIVE_URL` | Optional public service URL to ping. If omitted, the app uses Render's `RENDER_EXTERNAL_URL` when available, otherwise local `http://127.0.0.1:$PORT/health`. |

---

## 📦 Deployment to Render

1. Push this repository to GitHub (`https://github.com/Jitendra2007/telegramnewlink`).
2. In Render, click **New +** $\to$ **Web Service** $\to$ Connect `telegramnewlink`.
3. Choose **Python** runtime with Build Command `pip install -r requirements.txt` and Start Command `python main.py`.
4. Deploy and enjoy 24/7 automated monitoring!

> The service starts a background keep-alive loop after the HTTP server comes online. It pings `/health` every 13 minutes by default and logs each success/failure so Render logs show whether the site is being kept warm.
