# Cloud integration and data pipeline for the smart-home dashboard

Status: draft · Date: 2026-10-30

## Problem

The course report needs a working "cloud + big data" story for the smart-home app, at zero cost. Today:

- The ESP32 and the backend talk over the public `broker.hivemq.com` on plain TCP 1883 with no credentials. Anyone who guesses `MQTT_PREFIX` can publish `cmd/buzzer` or read the sensors.
- All history lives in one local SQLite file (`smart-home/backend/smarthome.db`, 5.4 MB). It is gone if the laptop is off or the file is lost, and nothing outside the laptop can see it.
- `readings` only grows. There are no rollups, no retention and no export. `GET /api/series` (`app/routers/dashboard.py:114`) reads only the newest `points * 10` rows, so `hours=168` actually shows about the last 1.6 hours.
- The dashboard has no login, so it cannot be exposed to the Internet safely.

Real volume is small: one ESP32 with 5 stored metrics (`temperature`, `humidity`, `ldr`, `gas`, `motion`), written every 10 s, which is about 43k rows a day or 16M a year. This is not big data by volume. The goal is to apply the right patterns at a scale that fits the project (managed broker, cloud time-series sink, rollups, a Parquet data lake, anomaly detection) and to be honest about that in the report.

## Goals

Delivered in 4 phases, in this order. Each phase can be merged and demoed on its own.

1. **Private MQTT broker with TLS.** ESP32, backend and simulator connect to a HiveMQ Cloud Serverless (free) cluster on 8883 with username/password.
2. **Cloud time-series sink.** The backend also pushes every stored reading to a cloud TSDB using Influx line protocol. A Grafana Cloud dashboard shows the history 24/7, even when the laptop is off.
3. **Local analytics pipeline.** Rollups by minute and hour, retention for raw rows, a daily Parquet export into a date-partitioned lake, rolling z-score anomaly events, and a new "Phân tích" page.
4. **Remote access.** Shared-password login with HMAC tokens on every dashboard API and on `/ws`. A script exposes the backend and frontend over Cloudflare quick tunnels.

## Non-goals

- Hosting the backend on a cloud VM or PaaS. Free tiers sleep or wipe disk, which breaks the always-on MQTT loop and SQLite. The backend stays on the laptop.
- Moving off SQLite to Postgres or Timescale.
- Multiple homes, multiple users or user accounts. There is one shared password.
- Changing MQTT topics or payloads. Only the transport (TLS, credentials) changes.
- Spark, Kafka, Flink or any cluster software. DuckDB is documented as a way to query the lake, not added as a dependency.
- ML models such as Isolation Forest or LSTM.
- FallGuard and Anti-theft apps.

## Design

### Phase 1: Private broker with TLS

- `smart-home/backend/app/config.py`: add `mqtt_tls: bool = False`.
- `smart-home/backend/app/mqtt_bridge.py` `start()`: when `settings.mqtt_tls`, call `client.tls_set()` before `connect_async`. This uses the OS CA store, and HiveMQ Cloud uses a Let's Encrypt chain. Log `tls=on/off` in the connect log line.
- `smart-home/backend/simulator_mqtt.py`: add `--user`, `--password`, `--tls`. Apply them with `username_pw_set` and `tls_set()`.
- `smart-home/firmware/esp32_smart_home/esp32_smart_home.ino`:
  - Replace `WiFiClient` with `WiFiClientSecure` and call `espClient.setCACert(ISRG_ROOT_X1)` with the PEM embedded as a `const char[]`.
  - Set `MQTT_PORT = 8883` and fill in `MQTT_USER` and `MQTT_PASS`.
  - Topics, payloads, buffer size and reconnect logic stay the same.
- HiveMQ Cloud console setup, documented in `smart-home/README.md`: create one cluster and two credentials, `esp32` and `backend`.
- Defaults stay `broker.hivemq.com:1883` with no TLS, so an unchanged `.env` behaves as before.

### Phase 2: Cloud time-series sink

New module `smart-home/backend/app/cloud_sink.py`. It uses `httpx`, which is already a dependency, so nothing new is added.

```python
def enqueue(device_code: str, fields: dict[str, float], ts: datetime) -> None  # sync, O(1)
async def flush() -> None      # POST one batch, called from background_worker
def status() -> dict           # {"enabled", "pending", "dropped", "last_ok", "last_error"}
```

- Buffer: `collections.deque(maxlen=CLOUD_SINK_MAX_BUFFER)`. When it is full, the oldest line is dropped and `dropped` goes up by one.
- Line format, one line per device per timestamp: `smarthome,device=esp32-main temperature=27.5,humidity=61,ldr=1203,gas=180,motion=0 1761800000000000000`, with the timestamp in ns. Grafana Cloud stores this as the Prometheus series `smarthome_temperature{device="esp32-main"}` and so on. InfluxDB stores it as measurement `smarthome`.
- Call sites:
  - `mqtt_bridge._store_readings()`: after the loop, enqueue the collected `values`.
  - `services.record_telemetry()`: enqueue the numeric metrics that were accepted.
- Flushing: `background_worker` in `app/main.py` calls `cloud_sink.flush()` when `CLOUD_SINK_INTERVAL` seconds have passed since the last flush. Each flush sends at most 1000 lines with a 10 s timeout.
- Auth: if `CLOUD_SINK_USER` is set, send Basic `(user, token)`; this is the Grafana Cloud case. Otherwise send `Authorization: Token <token>` for InfluxDB v2/v3 `/api/v2/write?bucket=...&precision=ns`. The exact URL comes from config.
- Error handling:

  | Result | Action |
  | --- | --- |
  | 2xx | Remove the batch from the buffer and set `last_ok`. |
  | 429, 5xx, timeout, connection error | Keep the batch. Back off 10 → 20 → 40 → 60 s (capped), honouring `Retry-After`. |
  | Other 4xx | Drop the batch, add its size to `dropped`, set `last_error`. Bad data will not fix itself. |

- `GET /api/health` gains `"cloud_sink": cloud_sink.status()`.
- Grafana dashboard export committed at `smart-home/cloud/grafana-dashboard.json`. It has one panel per metric plus a motion count per hour.

Why Grafana Cloud first: it stores the data and draws the dashboards from one free account (10k series, 14-day retention), and it accepts Influx line protocol directly. InfluxDB Cloud's free plan (30 days, 5 MB per 5 min) works with the same code by changing `CLOUD_SINK_URL`, user and token. Its signup status for new accounts in 2026 is unclear.

### Phase 3: Local analytics pipeline

New module `smart-home/backend/app/analytics.py`. It is driven from `background_worker` by wall-clock checks (once a minute and once a day), not on every 2 s tick.

**Rollups.** New model `ReadingRollup` in `app/models.py`. The bucket sizes are `1m` and `1h`.

- `run_rollups(db, now)` aggregates only fully closed buckets, starting from the newest `bucket_start` already stored for each bucket size and going up to `now` floored to the bucket.
- It writes with SQLite `INSERT … ON CONFLICT(device_id, metric, bucket, bucket_start) DO UPDATE`, so a re-run is idempotent.
- On first start it backfills from the oldest raw row, in chunks of one day.

**Parquet export.**

- `export_day(db, day)` writes `LAKE_DIR/readings/date=YYYY-MM-DD/part-0.parquet` with pyarrow (new dependency, approved).
- Columns: `device_code: string`, `metric: string`, `value: float64`, `ts: timestamp[us, tz=UTC]`, sorted by `ts`.
- It writes `part-0.parquet.tmp` first, then `os.replace`. An existing partition is skipped unless `force=True`.
- The daily job runs at the first tick after 00:10 UTC. It exports every closed day that has raw rows but no partition.
- Partitioning is by date only. Splitting by metric too would create tiny files at this volume.

**Retention**, run daily after the export:

- Delete raw `readings` older than `RAW_RETENTION_DAYS` (default 7), but only for days whose Parquet partition exists and whose `1h` rollups exist.
- Delete `1m` rollups older than 30 days.
- Keep `1h` rollups forever.

**Anomaly detection.** `detect_anomalies(db, now)` runs after each minute's rollup, for `temperature`, `humidity`, `gas` and `ldr`:

1. Take the newest closed `1m` bucket.
2. Compute the baseline mean and standard deviation from `1m` averages over the previous 24 h, excluding the current bucket.
3. Skip the check if there are fewer than 60 baseline buckets or the std is 0.
4. If `|z| > ANOMALY_Z` (default 3.0), create an event with `services.log_event(type="anomaly", severity="warning")`.
   - Message: `Bất thường: nhiệt độ 41.2 (z=4.3, TB 24h 28.1)`.
   - Cooldown: 15 min per `(device, metric)`, kept in memory.

**`/api/series` fix.** Same response shape. For `hours <= 6`, keep reading raw rows. For `hours <= 48`, read `1m` rollup averages. Otherwise read `1h` rollup averages. In each case, down-sample to `points`.

**API.** New router `app/routers/analytics.py`.

**Frontend.**

- New page `smart-home/frontend/src/app/analytics/page.tsx` titled "Phân tích".
- Sidebar entry in `src/components/Sidebar.tsx` with the lucide icon `BarChart3`.
- Page content:
  - A metric picker.
  - A 7-day hourly min/avg/max band chart (Recharts `Area` and `Line`).
  - A 24 h stats table.
  - The latest `anomaly` events (`GET /api/events?type=anomaly`).
  - The lake partitions table.
- Add the `anomaly` label "Bất thường" to `EVENT_LABEL` and to the filter list in `src/app/events/page.tsx`.
- New types and client calls in `src/lib/types.ts` and `src/lib/api.ts`.

Document how to query the lake with DuckDB in `smart-home/README.md`, for example `SELECT metric, date_trunc('hour', ts), avg(value) FROM 'data/lake/readings/*/*.parquet' GROUP BY ALL`.

### Phase 4: Login and tunnel

**Backend.**

- `smart-home/backend/app/security.py` adds:
  - `create_token() -> tuple[str, datetime]`, `verify_token(token) -> bool` and `require_user` (FastAPI dependency).
  - Token = `base64url(expiry_unix) + "." + base64url(HMAC_SHA256(AUTH_SECRET, expiry_unix))`, built with stdlib only and compared with `hmac.compare_digest`.
  - If `AUTH_SECRET` is empty, a random secret is generated at startup, so tokens expire on restart.
- If `DASHBOARD_PASSWORD` is empty, `require_user` allows everything (today's behaviour) and startup logs a warning.
- `require_user` applies to the routers `devices`, `events`, `automations`, `dashboard`, `live` and `analytics`. Exceptions:
  - `GET /api/devices/{code}/commands` keeps `require_device_key` only. Move it into a small device-facing router with the same path.
  - `/api/ingest/*` keeps `X-Device-Key`.
  - `/api/health` and `/api/auth/login` are public.
- New router `app/routers/auth.py`. Failed logins are rate-limited to 5 per client IP per minute, in memory. When behind the tunnel, the IP comes from `CF-Connecting-IP`.
- `/ws`: read `?token=`. If auth is enabled and the token is invalid, accept the connection, then `close(code=4401)`.

**Frontend.**

- New `src/app/login/page.tsx`: one password field and the button "Đăng nhập". Wrong password shows "Sai mật khẩu". Being rate-limited shows "Thử lại sau 1 phút".
- The token is stored in `localStorage` under the key `sh_token`.
- `src/lib/api.ts` `request()` adds `Authorization: Bearer`. On 401 it clears the token and redirects to `/login`.
- `WS_URL` appends `?token=`. In `DashboardProvider.tsx`, a socket closed with code 4401 redirects to `/login` instead of reconnecting.

**Tunnel script** `smart-home/scripts/tunnel.ps1`:

1. Abort if `cloudflared` is missing; tell the user to run `winget install Cloudflare.cloudflared`. Abort if `DASHBOARD_PASSWORD` is empty in `backend/.env`.
2. Start two quick tunnels, one for `localhost:8000` and one for `localhost:3000`. Read each `https://*.trycloudflare.com` URL from cloudflared's output.
3. Start the backend with `CORS_ORIGINS=<frontend url>,http://localhost:3000`. Start `npm run dev` with `NEXT_PUBLIC_API_URL=<backend url>`. Environment variables override `.env`.
4. Print both URLs. On Ctrl+C, stop all four processes.

## Data and API changes

**New table `reading_rollups`.** It is created by `Base.metadata.create_all`. No migration tool is needed, and existing tables are unchanged.

| column | type |
| --- | --- |
| id | int PK |
| device_id | FK devices.id ON DELETE CASCADE |
| metric | str(32) |
| bucket | str(4), `1m` or `1h` |
| bucket_start | datetime(tz) |
| count | int |
| min | float |
| max | float |
| avg | float |

Unique constraint on `(device_id, metric, bucket, bucket_start)`. Index on `(metric, bucket, bucket_start)`.

**New event type:** `anomaly`, severity `warning`.

**New endpoints.** Timestamps are UTC with a `Z` suffix, as everywhere else.

| Method and path | Auth | Response |
| --- | --- | --- |
| `POST /api/auth/login` `{password}` | public | `200 {token, expires_at}` · `401` · `429` |
| `GET /api/auth/me` | token | `200 {ok: true}` · `401` |
| `GET /api/analytics/rollups?metric=&bucket=1m\|1h&hours=1..720` | token | `[{bucket_start, min, max, avg, count}]` · `422` for an invalid bucket or hours |
| `GET /api/analytics/stats?hours=1..168` | token | `[{metric, min, max, avg, count, anomalies}]` |
| `GET /api/analytics/lake` | token | `[{date, rows, bytes}]`, newest first |

**Changed responses:**

- `GET /api/health` adds `cloud_sink`.
- `GET /api/series` keeps the same shape but serves long ranges from rollups.
- With a password set, all dashboard endpoints return 401 without a token.

**MQTT:** topics and payloads unchanged. Phase 1 changes only host, port, TLS and credentials, which means reflashing the ESP32.

**New config:**

| Variable | Default | Where |
| --- | --- | --- |
| `MQTT_TLS` | `false` | backend `.env` |
| `CLOUD_SINK_ENABLED` | `false` | backend `.env` |
| `CLOUD_SINK_URL` | empty | backend `.env` |
| `CLOUD_SINK_USER` | empty | backend `.env` |
| `CLOUD_SINK_TOKEN` | empty | backend `.env` |
| `CLOUD_SINK_INTERVAL` | `10` | backend `.env` |
| `CLOUD_SINK_MAX_BUFFER` | `10000` | backend `.env` |
| `LAKE_DIR` | `data/lake` | backend `.env` |
| `RAW_RETENTION_DAYS` | `7` | backend `.env` |
| `ANOMALY_Z` | `3.0` | backend `.env` |
| `DASHBOARD_PASSWORD` | empty | backend `.env` |
| `AUTH_SECRET` | empty | backend `.env` |
| `AUTH_TOKEN_HOURS` | `12` | backend `.env` |
| `MQTT_USER` / `MQTT_PASS` | (constants) | firmware |

Add `data/` to `smart-home/backend/.gitignore`. Update the env list in `.claude/CLAUDE.md`.

**New dependencies:**

- `pyarrow` in `requirements.txt` (approved).
- `pytest` in a new `requirements-dev.txt`. This still needs approval; see Open questions.
- `cloudflared` is an external tool, not a package dependency.

## Edge cases and errors

**Broker and network**

- Broker unreachable or wrong credentials: paho keeps retrying, as today. `/api/health` shows `mqtt_broker: false`. On the ESP32, local automation keeps working offline, as it does now.
- TLS on the ESP32: if the CA is wrong, `mqtt.state()` is `-2` and this appears in the serial log. The PEM must be the ISRG Root X1 that is valid until 2035.
- Cloud sink offline for hours: about 6 lines per minute means roughly 27 h fit in a 10k buffer before the oldest are dropped. A restart loses whatever is still buffered; that is accepted for a demo, and the local SQLite and Parquet are the source of truth.
- Cloud sink returns 400 for a bad field (for example NaN): `_num()` already filters NaN, and any remaining 4xx drops the batch, so a single bad line cannot block the queue.

**Data pipeline**

- Empty database: rollups, export, stats and anomaly detection do nothing. The analytics endpoints return `[]` and the page shows the empty state "Chưa có dữ liệu".
- Laptop off overnight: on the next start, rollups catch up from the watermark and the daily job exports every missing closed day. Retention never deletes a day without its Parquet partition.
- A crash mid-export leaves only a `.tmp` file. It is overwritten on the next run, and the partition is not treated as existing.
- Clock and timezone: all buckets and partitions use UTC days. The frontend converts to local time.
- Flat signals, such as `motion` or a constant `ldr`: std 0 means the check is skipped, and `motion` is excluded. A sensor glitch that sticks at one extreme fires once, then the 15 min cooldown applies.
- Concurrency: everything runs in the single `background_worker` task, so two rollups never run at once. SQLite writes from the MQTT handler and the worker stay serialized as they are today.

**Auth and tunnel**

- Tampered or expired token, or a password change: 401 and a redirect to `/login`. Changing `AUTH_SECRET` invalidates all tokens.
- Quick tunnel drops or its URL changes: re-run the script. URLs are random per run. This is documented, and named tunnels need a domain, so they are out of scope.

## Test plan

Add `smart-home/backend/tests/` with pytest and FastAPI `TestClient` (httpx is already installed). Use an in-memory SQLite engine, `MQTT_ENABLED=false` and `CLOUD_SINK_ENABLED=false` unless a test says otherwise.

**`test_cloud_sink.py`** (uses `httpx.MockTransport`)
- line format and ns timestamps
- 2xx drains the buffer
- 503 keeps the batch and backs off
- 400 drops the batch and counts it
- a full buffer drops the oldest

**`test_rollups.py`**
- 1m and 1h aggregates match hand-computed min, max, avg and count
- re-running is idempotent (same row count and values)
- an open bucket is not written
- catch-up after a gap of several hours

**`test_export_retention.py`**
- writes a partition with the right schema and row count (read back with pyarrow)
- skips an existing partition
- retention deletes raw rows only for exported days
- an orphan `.tmp` file is ignored

**`test_anomaly.py`**
- a spike at z ≥ 3 creates one `anomaly` event
- a second spike within 15 min does not create another
- fewer than 60 baseline buckets creates no event
- std 0 creates no event

**`test_auth.py`**
- login with the right password returns 200, the wrong one 401, and the 6th failure within a minute 429
- a dashboard endpoint returns 401 without a token and 200 with one
- an expired or tampered token returns 401
- `/api/ingest/telemetry` still works with `X-Device-Key` and no token
- `/ws` without a token closes with code 4401
- an empty `DASHBOARD_PASSWORD` keeps today's open behaviour

**`test_series.py`**
- `hours=168` returns points spanning more than 6 days when the data does

**Build checks**
- `.venv/Scripts/python -m compileall -q app simulator.py simulator_mqtt.py`
- `npx tsc --noEmit`
- `npm run build`

**End-to-end check**, run once per phase:

1. Start the backend with HiveMQ Cloud TLS credentials and `CLOUD_SINK_ENABLED=true`.
2. Run `simulator_mqtt.py --tls --user … --password … --gas-at 30` for 10 minutes. On a later phase, use the flashed ESP32 instead.
3. Confirm:
   - The dashboard updates live.
   - `/api/health` shows `mqtt_broker: true` and `cloud_sink.pending` near 0.
   - The Grafana dashboard shows the same values.
   - After `python -m app.analytics export --date <today> --force`, the Parquet file opens in DuckDB with the right row count.
4. Run `scripts/tunnel.ps1` and, from a phone on 4G:
   - log in
   - see live data
   - toggle the light in `manual` mode
   - get 401 after clearing `sh_token`

## Acceptance criteria

- [ ] `simulator_mqtt.py --tls --user <u> --password <p> --host <cluster>.hivemq.cloud --port 8883` publishes, and the backend with `MQTT_TLS=true` stores readings (`GET /api/readings` returns rows newer than 1 min).
- [ ] With `MQTT_TLS` unset and the default host, the backend connects to `broker.hivemq.com:1883` exactly as before.
- [ ] The firmware compiles with `WiFiClientSecure` on port 8883, and the serial log shows `MQTT: da ket noi` against the HiveMQ Cloud cluster.
- [ ] With `CLOUD_SINK_ENABLED=true` and valid Grafana Cloud credentials, `GET /api/health` shows a `cloud_sink.last_ok` newer than 30 s, and the query `smarthome_temperature` returns data in Grafana Explore.
- [ ] With the sink URL unreachable, the backend keeps serving `/api/live` and storing readings, and `cloud_sink.pending` grows.
- [ ] `pytest -q smart-home/backend/tests` passes, covering every test named in the test plan.
- [ ] `reading_rollups` contains `1m` and `1h` rows within 2 min of startup on a database that already has readings.
- [ ] `python -m app.analytics export --date YYYY-MM-DD` creates `data/lake/readings/date=YYYY-MM-DD/part-0.parquet`. DuckDB `SELECT count(*)` on it equals the raw row count for that UTC day.
- [ ] No raw reading older than `RAW_RETENTION_DAYS` remains for an exported day, and none is deleted for a day without a partition.
- [ ] Injecting a temperature spike (z > 3) through `POST /api/ingest/telemetry` creates exactly one `anomaly` event within 2 min.
- [ ] `GET /api/series?metrics=temperature&hours=168` returns points spanning more than 6 days on a database with 7 days of data.
- [ ] The `/analytics` page renders the band chart, stats, anomalies and lake table, and `npx tsc --noEmit` and `npm run build` pass.
- [ ] With `DASHBOARD_PASSWORD` set, `curl /api/devices` returns 401, `curl -H "Authorization: Bearer <token>" /api/devices` returns 200, and `/api/ingest/telemetry` with `X-Device-Key` returns 202.
- [ ] `scripts/tunnel.ps1` prints two `trycloudflare.com` URLs and refuses to start when `DASHBOARD_PASSWORD` is empty.
- [ ] The dashboard opened through the frontend tunnel URL logs in and receives WebSocket updates.

## Open questions

- Adding `pytest` as a dev dependency (`requirements-dev.txt`) has not been approved yet. The backend has no tests today.
- The user asked for InfluxDB Cloud + Grafana. This spec defaults to Grafana Cloud's Influx line-protocol endpoint (one account), with InfluxDB Cloud as a config-only alternative. Confirm this is acceptable.
- Should the HiveMQ `backend` credential be restricted by topic permissions (subscribe `sensors|status|mode`, publish `cmd/#|mode`), if the free tier allows it?
- Should a 7-day lake (Parquet) also be uploaded to free object storage, for example Cloudflare R2 at 10 GB free? That would need `boto3`, which is a new dependency.
