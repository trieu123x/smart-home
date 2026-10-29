# Web Push notifications — Smart Home (Android and iPhone)

This integration extends the existing FastAPI + Next.js dashboard; no firmware changes, Firebase, or Telegram replacement are needed.

## 1. Install dependencies and configure VAPID

In PowerShell (native deployment):

```powershell
cd smart-home\backend
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python generate_vapid.py
```

Paste the output values into `backend/.env`; replace the sample `VAPID_SUBJECT` with an email you control. Generate keys **only once**, keep the same pair for future builds. `backend/.env` is gitignored. Do not share `VAPID_PRIVATE_KEY` or put it into `NEXT_PUBLIC_*`.

For Docker: install `pywebpush` by rebuilding the backend and use the same `backend/.env` bind mount:

```powershell
cd smart-home
# The private/public VAPID values must already be present in backend/.env
# To generate keys on host, you can also run: py -3.13 -m pip install pywebpush==2.5.0
# and: py -3.13 backend/generate_vapid.py

docker compose up -d --build
```

## 2. Serve a public HTTPS URL

- Access the **Next.js dashboard** on HTTPS (e.g., via Tailscale Funnel or HTTPS reverse proxy). Frontend `/api/*` is already rewritten to the FastAPI backend.
- Both phone and desktop must use the **same origin** for a given installation. Subscriptions created at `localhost` will not work for your public HTTPS origin.
- No Firebase project and no separate public FastAPI URL required; FastAPI only needs outbound HTTPS to Apple/Google/Mozilla push services.
- If using a reverse proxy, forward the original host and HTTPS scheme. Login session cookies must remain secure and functional.

## 3. Android / iPhone

- Android Chrome: open the HTTPS dashboard, sign in, go to **Cảnh báo**, tap **Bật thông báo**, allow.
- iPhone iOS 16.4+: open the HTTPS dashboard, **Add to Home Screen**, **launch from the Home Screen icon**, sign in, open **Cảnh báo**, tap **Bật thông báo**, allow.
- Press **Gửi thử** to send an immediate test push to all registered installations. Then close the web app and repeat.
- Press **Tắt thông báo** to remove this installation. This project uses one shared dashboard password, so alerts are sent to **every registered installation**; there are not yet per-user notification preferences.

## 4. Events that generate Web Push

- Confirmed AI fall: `backend/app/fall_events.py`, after a deduplicated DB commit.
- ESP32 HTTP fall report: `backend/app/routers/ingest.py`, after DB commit.
- Gas rising-edge (`gas_alarm` false -> true): `backend/app/mqtt_bridge.py`, after DB commit.
- ESP32 offline transition: `backend/app/mqtt_bridge.py`, after DB commit.
- Existing MQTT, realtime WebSocket, SQLite event log, camera and Telegram functions stay in place.

## 5. Security and limitations

- Registration and test endpoints require the existing dashboard login. Known browser push-service hosts are allowlisted to prevent SSRF.
- The backend stores `endpoint`, `p256dh`, `auth` in `push_subscriptions` (SQLite) and removes subscriptions on HTTP 404/410 from push service.
- Shared dashboard login is in-memory; phone Push subscriptions are persisted and can still receive alerts after the browser session expires. Users on shared devices should disable push before leaving.
- Browser push is **best effort**; it may be delayed by network/power conditions. For safety-critical gas/fall alerts, keep the existing buzzer/Telegram and consider SMS as a fallback.
- This version sends a push request immediately after each event. For high-volume production systems, use a persistent outbox/background queue, push retry, alert escalation, and user-scoped permissions.
- If you change the VAPID key pair, all devices must register again.

## 6. Test

```powershell
cd smart-home\frontend
npm ci
npx tsc --noEmit
npm run build

cd ..\backend
.venv\Scripts\python -m pytest -q tests
```

`GET /api/push/public-key` returns 401 until login, 503 if VAPID is not configured, 200 on success.

`POST /api/push/test` is protected and rate-limited to 3 requests/minute per dashboard session.
