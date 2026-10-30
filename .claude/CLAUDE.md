# Smart Home (IoT course project)

Monorepo of three independent apps: an ESP32 smart-home dashboard, a camera fall-detection service (FallGuard) with Telegram alerts, and an anti-theft video analyzer. No shared code, no root build, no CI.

## Stack

- `smart-home/backend/`: Python 3.13 · FastAPI · SQLAlchemy 2 + SQLite · paho-mqtt (bridge to ESP32) · WebSocket `/ws`
- `smart-home/frontend/`: Next.js 14 App Router · React 18 · TypeScript · Tailwind 3 · Recharts · lucide-react
- `smart-home/firmware/esp32_smart_home/`: Arduino sketch for ESP32 (MQTT)
- `Fall detection/`: Python 3.11–3.13 · FastAPI · Ultralytics YOLO + PyTorch (CUDA) · OpenCV · ADB/scrcpy camera · pytest
- `Anti_theft_web/`: Python · FastAPI + Jinja2 · PyTorch · OpenCV

## Commands

Each app has its own venv / node_modules. Run commands from the app folder.

smart-home backend (`smart-home/backend/`):
- Install: `py -3.13 -m venv .venv` then `.venv/Scripts/python -m pip install -r requirements.txt`
- Dev: `.venv/Scripts/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
- Build check: `.venv/Scripts/python -m compileall -q app simulator.py simulator_mqtt.py`
- Simulate ESP32: `.venv/Scripts/python simulator_mqtt.py --prefix ptit_sh_k7x2q9/home/` (MQTT) or `simulator.py --interval 3` (HTTP)
- Test: `.venv/Scripts/python -m pip install -r requirements-dev.txt` then `.venv/Scripts/python -m pytest -q tests`
- Analytics CLI: `.venv/Scripts/python -m app.analytics export --date YYYY-MM-DD [--force]`

smart-home frontend (`smart-home/frontend/`):
- Install: `npm ci`
- Dev: `npm run dev` (http://localhost:3000)
- Build: `npm run build`
- Typecheck: `npx tsc --noEmit`
- No ESLint or Prettier installed: `npm run lint` opens an interactive setup prompt, don't run it.

FallGuard (`Fall detection/`):
- Install + run on Windows: `START_WINDOWS.bat` (creates `.venv`, installs CUDA torch via `fallguard.torch_setup`, then starts)
- Test (all): `.venv/Scripts/python -m pytest -q` (needs `pip install pytest httpx` first)
- Test (one): `.venv/Scripts/python -m pytest -q tests/test_adb_camera.py::test_one_device`

Anti-theft (`Anti_theft_web/`):
- Install: `pip install -r requirements.txt` in a venv; Dev: `python run.py` (http://127.0.0.1:8000)

## Layout

- Backend entry `smart-home/backend/app/main.py` (app, `/ws`, background loops); routes in `app/routers/`; rules engine in `app/services.py`; MQTT in `app/mqtt_bridge.py`.
- Frontend pages in `src/app/` (overview, devices, automations, events), API client and types in `src/lib/`.
- FallGuard package `Fall detection/fallguard/`; `Fall detection/server.py` is a compatibility shim for `uvicorn server:app`; static UI in `Fall detection/static/`.
- `Fall detection/tools/adb/` holds vendored adb.exe and scrcpy-server binaries. Don't edit.
- `Anti_theft_web/models/best_antitheft_v3.pt` is committed; FallGuard's YOLO weights (`models/detection/yolo11s.pt`, `models/pose_classification/leeyunjai-falldetect-11x.pt`) are not and must be copied in by hand.

## Conventions

- UI strings are Vietnamese with diacritics; keep them that way. Existing code comments are unaccented Vietnamese; write new ones in English.
- Backend stores and returns UTC with a `Z` suffix; the frontend converts to local time.
- MQTT topics and payloads (`sensors`, `status`, `mode`, `cmd/light|fan|buzzer` under `MQTT_PREFIX`) are a contract with the flashed ESP32 firmware. Changing them means reflashing; keep the backend and the `.ino` in sync.
- The 4 MQTT bridge devices (`esp32-main`, `light-main`, `fan-main`, `buzzer-main`) run their automation on the ESP32. Backend automation rules must reject them, and manual commands return HTTP 409 in `auto` mode.

## Gotchas

- All three Python apps default to port 8000. FallGuard honours `PORT`; Anti-theft hardcodes 8000 in `run.py`.
- `smart-home/backend/venv/` is a stale venv from another machine (gitignored). Use `.venv`.
- Python 3.15 is the default `python` on this machine; use `py -3.13` for venvs (wheels for 3.15 may be missing).
- Backend env vars (`smart-home/backend/.env`): `DATABASE_URL`, `DEVICE_API_KEY` (ESP32 sends it as `X-Device-Key`), `CORS_ORIGINS`, `MQTT_ENABLED`, `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS`, `MQTT_PREFIX`, `MQTT_OFFLINE_AFTER`, `MQTT_HISTORY_SECONDS`, `MQTT_TLS`, `SEED_DEMO`, `CLOUD_SINK_ENABLED`, `CLOUD_SINK_URL`, `CLOUD_SINK_USER`, `CLOUD_SINK_TOKEN`, `CLOUD_SINK_INTERVAL`, `CLOUD_SINK_MAX_BUFFER`, `LAKE_DIR`, `RAW_RETENTION_DAYS`, `ANOMALY_Z`, `DASHBOARD_PASSWORD`, `AUTH_SECRET`, `AUTH_TOKEN_HOURS`. Set `MQTT_ENABLED=false` to run without a broker. An empty `DASHBOARD_PASSWORD` leaves the dashboard APIs open.
- Frontend env vars (`.env.local`): `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_VIDEO_URL`.
- FallGuard env vars: `FALLGUARD_PASSWORD` (required, at least 12 chars), `CCTV_URL` (`adb:back|front|display`), `ADB_*`, `FALL_DEVICE`, `TELEGRAM_GATEWAY_URL`, `TELEGRAM_GATEWAY_KEY`. Telegram goes through a gateway, never the Bot API directly.
- FallGuard and `CHECK_ADB_CAMERA` both use ADB port 27183; don't run them at the same time. Tests mock ADB and don't prove real camera support.

## How we work

- Talk to me in Vietnamese. Write code, comments, commit messages and docs in English.
- Big or unclear work: `/spec` first, then `/feature <spec>`. Bugs: `/fix`. Before committing: `/ship`.
- If the diff fits in one sentence, skip the plan and just do it.
- Prove that work is done with evidence: the command you ran and its result. Never say "should work".
- Use the `test-runner` subagent for test or build runs with long output, `reviewer` before committing, `security-reviewer` when touching auth, input parsing, SQL, shell or network code, and `docs-researcher` for library questions.
- Follow the patterns already in the codebase. Don't add a dependency, change public APIs or touch unrelated code without asking.
- When compacting, keep the list of modified files, the active spec path, the test commands and any failing tests.
