# Unified Smart Home dashboard

The Smart Home backend now owns camera capture, YOLO Pose/BiLSTM inference,
incident persistence, WebSocket updates and Telegram delivery. The browser uses
one Next.js dashboard for devices, camera controls, AI and incident acknowledgement.
The experimental `Fall detection/` app is no longer required at runtime once its
local model and ADB assets have been migrated.

## Start on Windows

Install Python 3.13 with the Python launcher and Node.js 20 or 22 LTS, then run
`START_DASHBOARD.bat` from `smart-home/`. The first start creates `backend/.venv`,
installs dependencies and builds the frontend. Keep the terminal open; Ctrl+C
stops the backend and frontend. Later starts reuse the Python environment.

If `backend/.env` does not exist, the launcher imports the experimental camera
configuration. It reuses `FALLGUARD_PASSWORD` as the dashboard password when it is
at least 12 characters, otherwise prompts for a new password. The launcher writes
`DASHBOARD_PASSWORD` to the ignored `backend/.env`; credentials are never placed
in browser configuration. Existing `backend/.env` files are preserved.

When applying this integration to an older checkout without `backend/.env`, its
previous `.env.example` is saved as the ignored `.env` before the example template
is updated. This preserves existing MQTT/Telegram configuration. The launcher
fills in the gateway path used by the older sender if that setting is missing.

Model weights and bundled ADB tools are copied once from the experimental app to:

```text
backend/models/pose/yolo11n-pose.pt
backend/models/fall/best_fall_lstm.pth
backend/tools/adb/adb.exe
backend/tools/adb/scrcpy-server
```

On a fresh clone, copy these local assets before starting. They are ignored by Git.
The trained weights are unchanged. PyTorch's standard dependency installation
may use CPU depending on platform; provision the appropriate CUDA build separately
if GPU inference is required. `FALL_DEVICE=auto` uses CUDA when available.

Open **http://localhost:3000**, log in once, and use the Camera & Fall Detection
panel on Overview. Camera capture starts automatically by default; enable
**Phân tích AI** to start detection. Model/camera errors appear in that panel
while the rest of the dashboard remains available.

## Configuration

The backend reads `backend/.env`, not `.env.example`. Process environment wins.
Use `.env.example` as the template for a new configuration.

| Variable | Meaning |
|---|---|
| `DASHBOARD_PASSWORD` | Shared dashboard password, at least 12 characters |
| `FALL_ENABLED` | `true` to initialize camera/AI; `false` for sensors-only operation |
| `CCTV_URL` | `adb:back`, `adb:front` or `adb:display` |
| `CCTV_AUTOSTART` | `1` starts camera capture, `0` waits for the dashboard button |
| `CCTV_FALL_THRESHOLD` | BiLSTM decision threshold, default `0.80` |
| `CCTV_CONFIRMATIONS` | Consecutive positive windows, default `3` |
| `FALL_DEVICE` | `auto`, `cpu`, `cuda` or `cuda:0` |
| `FALL_ASSETS_DIR` | Optional directory containing `models/` and `tools/` |
| `TELEGRAM_GATEWAY_URL` | Gateway HTTPS origin |
| `TELEGRAM_GATEWAY_PATH` | Explicit gateway endpoint path |
| `TELEGRAM_GATEWAY_KEY` | Gateway authentication key |

For development, run the backend on loopback port 8000 and `npm run dev` in
`frontend/`. Leave `NEXT_PUBLIC_API_URL` empty: Next.js proxies `/api/*` and `/ws`
to `API_TARGET` (default `http://127.0.0.1:8000`). Remove any old
`NEXT_PUBLIC_API_URL=http://localhost:8000` override from `frontend/.env.local`.
For a separate reverse proxy, forward HTTP and WebSocket traffic and preserve
the original host and scheme. Add its public origin to `CORS_ORIGINS` if needed.

Backend API and WebSocket connections share one HttpOnly session cookie.
ESP32 ingest and command polling continue to use `X-Device-Key` independently.

## Incidents and alarms

Only confirmed falls produce incidents. The original 32-pose, 55-feature pipeline
and three-window confirmation logic are preserved. A unique detection key is
stored in the new `fall_incidents` table alongside the existing `events` table.
Existing tables and event history are preserved. Retrying persistence with the
same key does not create duplicate history records. Dashboard events are published
after the transaction commits. Telegram failure does not erase a saved incident.
Pending delivery retries are in memory; stopping the process interrupts unfinished
delivery jobs. Saved incident history survives restart.

Reflash the updated `firmware/esp32_smart_home/esp32_smart_home.ino` to enable
camera-triggered buzzer alarms. The additional command is:

```text
<MQTT_PREFIX>cmd/fall_alarm = ON
```

It activates the buzzer for 30 seconds in either auto or manual mode, without
changing the mode or the light/fan commands. The normal gas alarm remains active
independently. No command is retained or replayed to an offline ESP32. Firmware
without this addition continues to work for existing controls but ignores camera
alarm commands. Acknowledging a dashboard incident records that it was handled;
the timed hardware alarm expires independently.

## Validation

```powershell
cd backend
.venv\Scripts\python -m pip install -r requirements-test.txt
.venv\Scripts\python -m pytest -q tests
cd ../frontend
npm ci
npx tsc --noEmit
npm run build
```

Integration tests use a simulated camera and classifier and disable MQTT/Telegram
network delivery. They validate routing, sessions, incident persistence, confirmation
logic and acknowledgement. They do not validate recognition accuracy, actual Android
capture, CUDA, Telegram delivery or an attached ESP32. Verify those with local
hardware before relying on the live system.
