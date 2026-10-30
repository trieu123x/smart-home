# Smart Home Dashboard (đồ án IoT với ESP32)

Dashboard giám sát và điều khiển nhà thông minh, gồm **backend FastAPI + SQLite** và
**frontend Next.js + TailwindCSS + Recharts + lucide-react**. Phần thiết bị thật (ESP32)
chỉ cần gọi vài endpoint HTTP là ghép được.

Ba chức năng chính:

| Chức năng | Cách hoạt động |
|---|---|
| **Phát hiện ngã** | ESP32 gửi `POST /api/ingest/event` (hoặc metric `fall = 1`) → backend ghi cảnh báo mức `critical`, bật còi báo 30 giây và đẩy banner đỏ lên dashboard theo thời gian thực |
| **Tự động bật quạt** | Luật `nhiệt độ > 30°C → bật quạt` và `nhiệt độ < 27°C → tắt quạt` |
| **Bật đèn khi có chuyển động** | Luật `motion ≥ 1 → bật đèn`, tự tắt sau 30 giây nếu không còn chuyển động |

Các luật này nằm trong bảng `automations`, sửa được ngay trên giao diện — không cần nạp lại firmware.

## Chạy với ESP32 qua MQTT (chế độ Tự động / Thủ công)

Bản này đã ghép sẵn chức năng của project Django `smarthome (Django)` vào kiến trúc
FastAPI + Next.js. **ESP32 giao tiếp qua MQTT với đúng giao thức cũ nên firmware đang chạy với
bản Django không cần sửa.**

```
ESP32 ──MQTT──► [broker] ◄──MQTT── FastAPI (backend/app/mqtt_bridge.py) ──WebSocket──► Next.js
```

| Topic (prefix `MQTT_PREFIX`, mặc định `ptit_sh_k7x2q9/home/`) | Hướng | Nội dung |
|---|---|---|
| `sensors` | ESP32 → server | JSON `{ldr, dark, temp, hum, gas, gas_alarm, motion, mode, light, fan, buzzer}` |
| `status` | ESP32 → server | `online` / `offline` (Last Will) |
| `mode` | hai chiều, retained | `auto` / `manual` |
| `cmd/light`, `cmd/fan`, `cmd/buzzer` | server → ESP32 | `ON` / `OFF` |

- **Tự động**: ESP32 tự chạy logic như code C++ hiện tại, web chỉ hiển thị.
- **Thủ công**: ESP32 chỉ gửi cảm biến, đèn/quạt/loa chỉ đổi khi bấm Bật/Tắt trên web.
  Server từ chối lệnh (HTTP 409) nếu đang ở chế độ tự động.

Cấu hình trong `backend/.env` (xem `.env.example`): `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`,
`MQTT_PASS`, `MQTT_PREFIX`. Các biến này tương ứng với `settings.py` của bản Django.

Điểm khác với phần HTTP cũ:

- Backend tự tạo 4 thiết bị: `esp32-main` (cảm biến), `light-main`, `fan-main`, `buzzer-main`.
  Dữ liệu demo chỉ tạo khi đặt `SEED_DEMO=true`.
- **Luật ở trang Tự động hóa không điều khiển được 4 thiết bị này** vì logic tự động nằm trên ESP32
  (backend sẽ báo lỗi nếu tạo luật nhắm vào chúng). Luật vẫn dùng bình thường cho thiết bị HTTP.
- Lịch sử cảm biến lưu vào SQLite mỗi `MQTT_HISTORY_SECONDS` giây (mặc định 10), còn giao diện
  nhận từng bản tin realtime qua WebSocket (kênh `live`).
- Khung **Camera** trên trang Tổng quan để trống; đặt `NEXT_PUBLIC_VIDEO_URL` trong
  `frontend/.env.local` để hiện luồng video.
- Cảnh báo gas/khói: banner đỏ trên đầu trang, ghi sự kiện `gas_alarm` vào nhật ký.

Endpoint mới: `GET /api/live`, `POST /api/mode {"mode":"auto|manual"}`,
`POST /api/command {"device":"light|fan|buzzer","state":true}`.

**Chạy thử khi chưa có ESP32**:

```bash
cd backend
python simulator_mqtt.py --prefix ptit_sh_k7x2q9/home/ --gas-at 20
```

Giả lập đúng giao thức trên (có cả chế độ auto/manual). Trong lúc chạy gõ `g`/`m`/`d` + Enter để
bật/tắt rò gas, chuyển động, trời tối.

> Broker công cộng `broker.hivemq.com` không có mật khẩu: ai biết prefix đều đọc/điều khiển được.
> Khi triển khai thật hãy dùng broker riêng (Mosquitto) có user/password và prefix khó đoán.

## Cấu trúc thư mục

```
smart-home/
├── backend/            FastAPI + SQLAlchemy + SQLite
│   ├── app/
│   │   ├── main.py         khởi tạo app, WebSocket /ws, vòng lặp nền
│   │   ├── models.py       Device, Reading, Event, Automation, Command
│   │   ├── schemas.py      Pydantic schema
│   │   ├── services.py     ghi telemetry, chạy luật tự động, hẹn giờ tắt
│   │   ├── mqtt_bridge.py  cầu nối MQTT <-> backend (cảm biến, chế độ auto/manual, lệnh)
│   │   ├── bridge_devices.py  mã 4 thiết bị ESP32 nối qua MQTT
│   │   ├── seed.py         tạo sẵn thiết bị + luật + dữ liệu mẫu
│   │   └── routers/        devices, events, automations, dashboard, ingest
│   ├── simulator.py       giả lập ESP32 qua HTTP
│   └── simulator_mqtt.py  giả lập ESP32 qua MQTT (auto/manual)
├── frontend/           Next.js 14 App Router
│   └── src/
│       ├── app/            4 trang: tổng quan, thiết bị, tự động hóa, cảnh báo
│       ├── components/     biểu đồ, thẻ thiết bị, feed sự kiện, banner ngã
│       └── lib/            gọi API, kiểu dữ liệu, màu biểu đồ, định dạng
└── firmware/           sketch Arduino mẫu cho ESP32
```

## Chạy dự án

### 1. Backend

```bash
cd backend
py -3.13 -m venv .venv            # Windows; macOS/Linux: python3 -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # macOS/Linux: cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API docs: <http://localhost:8000/docs>
- `--host 0.0.0.0` là bắt buộc nếu muốn ESP32 trong cùng WiFi gọi vào được.
- Lần chạy đầu tiên sẽ tự tạo `smarthome.db`, 7 thiết bị mẫu, 4 luật tự động và
  12 giờ dữ liệu giả để biểu đồ không trống.

### 2. Frontend

```bash
cd frontend
npm install
copy .env.local.example .env.local
npm run dev
```

Mở <http://localhost:3000>.

### 3. Giả lập ESP32 (khi chưa có thiết bị thật)

```bash
cd backend
.venv\Scripts\python simulator.py --interval 3
```

Script gửi nhiệt độ/độ ẩm/ánh sáng/chuyển động liên tục và thỉnh thoảng bắn một cảnh
báo ngã, đủ để quay video demo đồ án.

## API cho ESP32

Mọi request từ thiết bị phải kèm header `X-Device-Key` (mặc định `esp32-secret-key`,
đổi trong `backend/.env`).

**Gửi số liệu cảm biến**

```http
POST /api/ingest/telemetry
X-Device-Key: esp32-secret-key

{
  "device_code": "esp32-phongkhach",
  "metrics": { "temperature": 31.2, "humidity": 68, "lux": 40, "motion": 1 }
}
```

Thiết bị chưa có trong CSDL sẽ được tự động đăng ký, sau đó vào trang **Thiết bị**
đổi tên và gán phòng.

**Báo sự kiện ngã**

```http
POST /api/ingest/event
X-Device-Key: esp32-secret-key

{
  "device_code": "esp32-nhatam",
  "type": "fall_detected",
  "severity": "critical",
  "message": "Phát hiện ngã tại nhà tắm"
}
```

**Nhận lệnh bật/tắt relay** — ESP32 gọi định kỳ (2 giây/lần), lệnh trả về sẽ bị đánh
dấu đã nhận nên không bị lặp:

```http
GET /api/devices/fan-phongkhach/commands
X-Device-Key: esp32-secret-key

[{ "id": 12, "action": "on", "source": "automation", "created_at": "..." }]
```

## Các endpoint khác

| Method | Đường dẫn | Công dụng |
|---|---|---|
| GET | `/api/summary` | số liệu cho hàng thẻ KPI |
| GET | `/api/devices` | danh sách thiết bị |
| POST | `/api/devices/{id}/toggle` | bật/tắt thủ công từ dashboard |
| PATCH | `/api/devices/{id}` | đổi tên, phòng, bật/tắt chế độ AUTO |
| GET | `/api/series?metrics=temperature,humidity&hours=12` | dữ liệu biểu đồ đường |
| GET | `/api/activity?hours=24` | số sự kiện theo giờ cho biểu đồ cột |
| GET | `/api/events?limit=50` | nhật ký sự kiện |
| POST | `/api/events/{id}/ack` | xác nhận đã xử lý cảnh báo |
| GET/POST/PATCH/DELETE | `/api/automations` | quản lý luật tự động |
| WS | `/ws` | kênh realtime đẩy `device` / `event` / `reading` / `automation` |
| POST | `/api/auth/login` | `{password}` → `{token, expires_at}` (public, 5 failures/min/IP) |
| GET | `/api/analytics/rollups?metric=temperature&bucket=1h&hours=168` | min/avg/max per bucket |
| GET | `/api/analytics/stats?hours=24` | per-metric stats and anomaly count |
| GET | `/api/analytics/lake` | Parquet partitions, newest first |
| GET | `/api/health` | public; includes `mqtt_broker` and `cloud_sink` status |

## Cloud and data pipeline

Everything below is free-tier and optional. With an unchanged `.env` the app behaves
as before (public `broker.hivemq.com:1883`, no cloud sink, no login).

### Private MQTT broker (HiveMQ Cloud, TLS)

1. Create a free **HiveMQ Cloud Serverless** cluster at console.hivemq.cloud.
2. Under *Access Management*, create two credentials: `esp32` and `backend`
   (publish + subscribe).
3. Backend `.env`:
   ```
   MQTT_HOST=<cluster-id>.s1.eu.hivemq.cloud
   MQTT_PORT=8883
   MQTT_TLS=true
   MQTT_USER=backend
   MQTT_PASS=<backend password>
   ```
   The backend log shows `da ket noi broker ... tls=on`.
4. Firmware: set `MQTT_HOST`, `MQTT_USER=esp32` and `MQTT_PASS` at the top of
   `esp32_smart_home.ino` and reflash. It uses `WiFiClientSecure` on port 8883 with the
   ISRG Root X1 CA embedded (valid until 2035). A wrong CA shows `MQTT: loi rc=-2`.
5. Simulator: `python simulator_mqtt.py --host <cluster>.s1.eu.hivemq.cloud --port 8883 --tls --user esp32 --password <p>`.

Topics and payloads are unchanged; only host, port, TLS and credentials differ.

### Cloud time-series sink (Grafana Cloud)

The backend pushes every stored reading in Influx line protocol
(`smarthome,device=esp32-main temperature=27.5,humidity=61,... <ns>`), buffered in memory
and flushed every `CLOUD_SINK_INTERVAL` seconds. If the cloud is down the buffer keeps
up to `CLOUD_SINK_MAX_BUFFER` lines (about 27 h at the ESP32 rate) and retries with
back-off; SQLite stays the source of truth.

1. Create a free Grafana Cloud stack. In *Connections → Add new connection → InfluxDB*
   (or the stack's *Details* page) find the Influx write endpoint, the instance ID and
   create an access policy token with `metrics:write`.
2. Backend `.env`:
   ```
   CLOUD_SINK_ENABLED=true
   CLOUD_SINK_URL=https://influx-<region>.grafana.net/api/v1/push/influx/write
   CLOUD_SINK_USER=<instance id>
   CLOUD_SINK_TOKEN=<access policy token>
   ```
3. `GET /api/health` → `cloud_sink.last_ok` updates every few seconds.
4. In Grafana, *Dashboards → New → Import* `cloud/grafana-dashboard.json` and pick the
   stack's Prometheus data source. Series are named `smarthome_temperature{device="esp32-main"}` etc.

InfluxDB Cloud works with the same code: leave `CLOUD_SINK_USER` empty and set
`CLOUD_SINK_URL=https://<host>/api/v2/write?bucket=<bucket>&org=<org>&precision=ns`
and `CLOUD_SINK_TOKEN=<API token>`.

### Local analytics pipeline

The background worker, with no extra setup:

- **Rollups** (`reading_rollups` table): min/max/avg/count per device and metric for every
  closed 1-minute and 1-hour bucket. `/api/series` serves ranges over 6 h from them.
- **Parquet lake**: after 00:10 UTC each day, every closed UTC day is written to
  `LAKE_DIR/readings/date=YYYY-MM-DD/part-0.parquet` (columns `device_code`, `metric`,
  `value`, `ts`). Manual export: `python -m app.analytics export --date 2026-10-29 [--force]`.
- **Retention**: raw readings older than `RAW_RETENTION_DAYS` (7) are deleted, but only for
  days that have a Parquet partition and hourly rollups. 1m rollups are kept 30 days, 1h forever.
- **Anomalies**: each minute, the newest 1m average of temperature, humidity, gas and LDR
  is compared with the previous 24 h of 1m averages. `|z| > ANOMALY_Z` (3.0) logs an
  `anomaly` event (15 min cooldown per device and metric).

The "Phân tích" page shows the 7-day hourly band chart, 24 h stats, anomalies and the lake.

Query the lake with [DuckDB](https://duckdb.org/) (not a project dependency), from `backend/`:

```sql
SELECT metric, date_trunc('hour', ts) AS hour, avg(value)
FROM 'data/lake/readings/*/*.parquet'
GROUP BY ALL ORDER BY hour;
```

Scale, honestly: one ESP32 writes about 43k rows a day (16M a year). That is small data;
the point is to use the patterns (managed broker, cloud TSDB, rollups, a partitioned
columnar lake, streaming anomaly detection) at a size that fits the project.

### Login and remote access (Cloudflare quick tunnel)

1. In `backend/.env` set `DASHBOARD_PASSWORD` (at least 12 characters), a long random
   `DEVICE_API_KEY` (the default `esp32-secret-key` is public), and optionally a fixed
   `AUTH_SECRET`. All dashboard APIs and `/ws` then need a token from
   `POST /api/auth/login`; `/api/ingest/*` and `/api/devices/{code}/commands` keep `X-Device-Key`.
2. Install cloudflared: `winget install Cloudflare.cloudflared`. Stop anything on ports 8000 and 3000.
3. Run `powershell -ExecutionPolicy Bypass -File scripts\tunnel.ps1`. It starts the
   frontend tunnel, then the backend, checks on the running backend that login is
   enforced and the default device key is rejected, then opens the backend tunnel and
   builds and starts the frontend in production mode. It prints the dashboard URL;
   Ctrl+C stops everything. URLs are random on every run; if a tunnel drops, run it again.

## Ghi chú kỹ thuật

- **Chế độ AUTO**: mỗi thiết bị chấp hành có cờ `auto_mode`. Tắt cờ này thì các luật
  tự động bỏ qua thiết bị đó, dùng khi muốn giữ nguyên trạng thái do người dùng đặt.
- **Chống nhấp nháy**: mỗi luật có `cooldown_seconds` (khoảng chờ tối thiểu giữa hai
  lần kích hoạt) và `auto_off_seconds` (tự tắt sau bao lâu). Khi cảm biến vẫn báo
  chuyển động, thời gian tự tắt được gia hạn thay vì tắt đèn giữa chừng.
- **Mất kết nối**: thiết bị không gửi dữ liệu quá 60 giây bị đánh dấu offline và ghi
  một sự kiện cảnh báo.
- **Thời gian**: backend lưu và trả về UTC (có hậu tố `Z`), frontend tự đổi sang giờ
  máy người dùng.
- **Màu biểu đồ** đã được kiểm tra tương phản ≥ 3:1 trên nền tối và phân biệt được
  với người mù màu; chú giải luôn kèm biểu tượng chứ không phân biệt bằng riêng màu.
- Nhiệt độ, độ ẩm, ánh sáng có thang đo khác nhau nên biểu đồ cho chọn từng chỉ số
  thay vì vẽ chung hai trục y.

## Hướng phát triển thêm

- Đăng nhập cho người nhà (JWT) và phân quyền xem/điều khiển.
- Gửi thông báo Telegram/Zalo khi phát hiện ngã.
- Lưu lịch sử dài hạn sang PostgreSQL/TimescaleDB thay cho SQLite.
