# Smart Home Dashboard (đồ án IoT với ESP32)

## Unified dashboard with Fall Detection

Run `START_DASHBOARD.bat` to use one dashboard for ESP32 devices, camera controls,
YOLO Pose/BiLSTM fall detection, Telegram alerts and shared incident history.
See [setup, configuration and validation](docs/FALL_DETECTION_INTEGRATION.md).
The backend reads `.env`; set `DASHBOARD_PASSWORD` (at least 12 characters).
Reflash the updated ESP32 firmware to enable camera-triggered timed buzzer alarms.


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
