# FallGuard CCTV - ket noi Telegram Gateway hien co

Project nhan dien nga (FastAPI + YOLO + Camera + MediaMTX). **FallGuard chi goi HTTP Gateway**, KHONG dung Telegram Bot Token, Chat ID hay Supabase trong project nay. Bot Telegram + Gateway dang chay tren Vercel; Supabase hien co cua bot quan ly nguoi dung `/start`.

## So do hoat dong

```text
Camera -> FallGuard (Windows/server co GPU, YOLO, dashboard)
                | HTTPS POST /gateway/v1/notify
                | Header: X-Gateway-Key
                v
Telegram-bot Gateway (Vercel, project DA CO)
                | Su dung bot token + Supabase trung tam
                v
Tat ca nguoi dung da /start, chua /stop
```

## 1. Vercel (bot Telegram, KHONG PHAI FallGuard)

Giữ nguyên Vercel Project/Supabase/bot token cũ. Bản Telegram Gateway phải có endpoint `POST /gateway/v1/notify` (được cung cấp trong bản bot đã sửa trước đó).

Trong Vercel **Settings -> Environment Variables**, giữ các biến cũ và thêm/kiểm tra:

```env
GATEWAY_API_KEYS=fall_detection:KHOA_NGAU_NHIEN_CHO_FALLGUARD;flood_detection:KHOA_KHAC
```

Tạo khóa ngẫu nhiên riêng cho FallGuard:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Khóa không đưa lên GitHub. Sau khi cập nhật biến môi trường, **redeploy Production**. Đảm bảo đã chạy hai bảng Gateway `bot_alert_subscribers` và `bot_gateway_events` trong Supabase cũ (chỉ cần làm một lần). Người dùng nhắn `/start` để nhận cảnh báo và `/stop` để tắt.

## 2. FallGuard (máy đang chạy nhận diện ngã)

Nếu đã có `.env`, **giữ nguyên và sao lưu nó**, chỉ xóa hai biến cũ `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (nếu có), rồi thêm hai biến mới:

```dotenv
TELEGRAM_GATEWAY_URL=https://TEN-PROJECT-VERCEL-CUA-BAN.vercel.app
TELEGRAM_GATEWAY_KEY=KHOA_NGAU_NHIEN_CHO_FALLGUARD
ALERT_COOLDOWN_SECONDS=60
```

- `TELEGRAM_GATEWAY_URL` là URL gốc của Vercel Production, không có `/gateway/v1/notify`.
- `TELEGRAM_GATEWAY_KEY` trùng chính xác với khóa phía sau `fall_detection:` trong `GATEWAY_API_KEYS` ở Vercel.
- Dùng HTTPS (không chấp nhận HTTP hoặc redirect để bảo vệ API key).
- **Không** đưa token, chat ID hoặc khóa Supabase vào project FallGuard.
- Giữ nguyên `CCTV_URL`, `CCTV_NAME`, `FALLGUARD_PASSWORD`, cấu hình model và GPU trước đó.

Nếu chạy trên Windows, sử dụng lại `START_WINDOWS.bat`. Để test, mở dashboard, đăng nhập rồi nhấn **Gửi thử Telegram**. Nút này gọi `/api/telegram/test` trên FallGuard, sau đó FallGuard gọi Gateway, Gateway broadcast cho tất cả người đã `/start`. Frontend không giữ API key.

## 3. Cảnh báo thực tế

Khi AI phát hiện tư thế ngã **ít nhất 5 giây** (giữ nguyên logic gốc), FallGuard gửi JSON:

```http
POST https://TEN-PROJECT-VERCEL-CUA-BAN.vercel.app/gateway/v1/notify
X-Gateway-Key: <TELEGRAM_GATEWAY_KEY>
Content-Type: application/json
```

```json
{
  "title": "FALLGUARD - CẢNH BÁO TÉ NGÃ",
  "level": "critical",
  "message": "Phát hiện dấu hiệu người bị ngã. Camera: Camera 01. Điểm model: 95%...",
  "event_id": "fallguard-uuid"
}
```

`event_id` riêng cho mỗi sự kiện và giữ nguyên nếu lần gửi phải retry, giúp Gateway chặn gửi trùng. FallGuard vẫn giữ cooldown theo người và session; không thay đổi YOLO, camera hay logic 5 giây.

### Giới hạn hiện tại

- **Ảnh JPEG không được gửi kèm Telegram nữa.** Gateway đã deploy chỉ chấp nhận JSON văn bản và từ chối `photo_b64`; ảnh vẫn hiển thị trên dashboard FallGuard. Để gửi ảnh đến tất cả người dùng, cần mở rộng **gateway trung tâm**, không gọi Telegram Bot API trực tiếp từ FallGuard.
- Broadcast của Gateway đang gửi đồng bộ trong request Vercel; nếu đông người, request có thể chạm giới hạn thời gian. Việc xử lý hàng đợi nằm ở phía Gateway.
- Gateway chống gửi trùng theo `event_id` ở mức "at most once". Nếu lỗi xảy ra sau khi chỉ gửi cho một số người, retry cùng `event_id` không gửi lại cho phần còn lại. Muốn đảm bảo từng người đều nhận, cần hàng đợi theo người nhận tại Gateway.
- Nếu chưa có người đăng ký `/start`, nút test sẽ báo không gửi thành công.

## 4. Camera, GPU, MediaMTX

Các chức năng này **không đổi**. Dùng model weights tại:

- `models/detection/yolo11s.pt`
- `models/pose_classification/leeyunjai-falldetect-11x.pt`

Nếu đã có `mediamtx.yml`, `LARIX_CONNECTION.txt`, `auto.key`, `auto.crt` trên máy hiện tại, **giữ lại tại chỗ, không xóa và không ghi đè**. Các file này bị loại khỏi ZIP phát hành vì chứa mật khẩu camera hoặc khóa TLS. Nếu cài máy mới, chạy `SETUP_CAMERA_RECEIVER.bat` để tạo credentials riêng, sau đó `RUN_MEDIAMTX.bat`. Đừng public MediaMTX admin API hoặc camera credentials.

### Khắc phục lỗi camera nhận stream nhưng FallGuard báo RTSP 401

Nếu cửa sổ MediaMTX hiện `is publishing to path 'live/fallguard'`, nhưng
FallGuard hiển thị `DESCRIBE failed: 401 Unauthorized` hoặc màn hình luôn
"đang kết nối lại", nghĩa là **mật khẩu đọc RTSP trong `.env` không khớp**
với tài khoản `fallguard_read` trong `mediamtx.yml`.

1. Đóng cửa sổ `START_WINDOWS.bat` (không cần tắt MediaMTX/Larix).
2. Nhấn đúp **`REPAIR_CAMERA_AUTH.bat`** ở thư mục gốc FallGuard.
3. Script tự đọc tài khoản `fallguard_read` của `mediamtx.yml`, sao lưu `.env`
   lần đầu vào `.env.backup.camera-auth` và chỉ cập nhật **`CCTV_URL`**.
4. Chạy lại `START_WINDOWS.bat` rồi nhấn **Kết nối camera** trên dashboard.

Công cụ không tạo mật khẩu mới, không thay đổi cấu hình publish/Larix,
không động vào Telegram Gateway hoặc mật khẩu dashboard. Nó sẽ từ chối
chỉnh nếu `CCTV_URL` là camera RTSP bên ngoài hoặc có cấu hình khác.
`START_WINDOWS.bat` cũng có bước kiểm tra sự khớp credentials khi khởi động,
nhưng chỉ cảnh báo, không tự ý thay đổi `.env`. Nếu bạn đã tự đặt biến
`CCTV_URL` ở Windows, biến đó sẽ được ưu tiên hơn `.env`; cần bỏ hoặc
sửa biến môi trường Windows nếu nó đang trỏ sai.

**Không gửi/commit** `.env`, `mediamtx.yml`, `LARIX_CONNECTION.txt` và
`.env.backup.camera-auth`: các file này có thể chứa mật khẩu hoặc URL riêng tư.

## 5. Kiểm tra code (không gửi Telegram thật)

```bash
python -m pip install pytest httpx pyyaml
python -m pytest -q tests/test_telegram_gateway.py tests/test_gateway_route.py tests/test_cctv_5s.py tests/test_torch_gpu.py
```

Lỗi phổ biến: `401` sai Gateway API key; `404` bot Vercel chưa deploy route; `503` Gateway/Supabase chưa sẵn sàng; `sent=0` bot chưa có người dùng `/start`.

## File thay đổi

- `fallguard/telegram_config.py`: đọc Gateway URL/key từ `.env`.
- `fallguard/telegram_client.py`: thay Telegram Bot API bằng Gateway JSON client.
- `fallguard/server.py`: test/alert gọi gateway, bảo toàn detect và cooldown.
- `.env.example`: chỉ còn Gateway URL/key.
- `tests/test_telegram_gateway.py`: test endpoint, header, status, lỗi và giữ bí mật.
- `README.md`: hướng dẫn đúng với Telegram Gateway hiện có; bỏ tài liệu Next.js route cũ không tồn tại.

## Ban ZIP da don sach

Ban ZIP duoc dong goi de chia se source code an toan: da loai moi thu muc `__pycache__/` va `.pytest_cache/`, test Node.js cu `tests/test_gateway_vercel.mjs` (tham chieu den `vercel-gateway/` khong con ton tai), va 4 file cau hinh rieng tu `mediamtx.yml`, `LARIX_CONNECTION.txt`, `auto.crt`, `auto.key`.

**Neu nang cap tren may da chay:** KHONG xoa / ghi de `.env`, `mediamtx.yml`, `LARIX_CONNECTION.txt`, model weights trong `models/` hay MediaMTX trong `tools/`. Chi chep de cac file code tu ban ZIP. Neu dang bi RTSP 401, giu `mediamtx.yml` goc de `REPAIR_CAMERA_AUTH.bat` dong bo dung credential.

**Neu cai moi:** chay `START_WINDOWS.bat` de tao `.env` va nhap mat khau dashboard, tiep do chay `SETUP_CAMERA_RECEIVER.bat` de tao tai khoan publish/read va tai MediaMTX. Tai model weights theo cau hinh project, sau do ket noi Larix / Tailscale. Khong commit file bi mat vao GitHub.

## Giam do tre camera (RTSP / OpenCV)

Neu hinh anh trong FallGuard cham nhieu giay so voi thuc te, them vao `.env`:

```dotenv
CCTV_LOW_LATENCY=1
```

Dung `START_WINDOWS.bat` va chay lai de mo luong RTSP moi. Duong dan camera `CCTV_URL` va mat khau MediaMTX giu nguyen. Chuc nang nay config `OPENCV_FFMPEG_CAPTURE_OPTIONS` (TCP, `nobuffer`, `low_delay`) cho **luong RTSP**, khong anh huong den HTTP stream. Neu khong doc duoc video / giat manh, doi `CCTV_LOW_LATENCY=0` va khoi dong lai. Neu Windows da co `OPENCV_FFMPEG_CAPTURE_OPTIONS` rieng, ban patch se khong ghi de.

**Khong dam bao tri het 12 giay:** camera qua Larix -> Tailscale Funnel -> MediaMTX -> OpenCV. OpenCV co the giam buffer phia nhan nhung khong the sua buffering tai nguon. De phan biet, xem cung luong RTSP bang VLC (Network caching 100-300 ms). Neu VLC cung cham nhieu giay, xem lai Larix (H.264, 720p, 25/30 FPS, bitrate ~1.5-2 Mbps, keyframe 1-2 giay, bo phat thich ung cho upload khong on dinh) va duong mang. Neu VLC gan real time ma dashboard cham, kiem tra OpenCV, CPU, khung hinh JPEG va browser. Khong chia se URL RTSP chua mat khau.

Delay camera KHAC 5 giay AI can de xac nhan nga, va KHAC thoi gian Telegram Gateway gui tin.
