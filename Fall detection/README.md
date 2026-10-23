# FallGuard — Camera Android qua cáp USB + ADB

Ứng dụng FallGuard (FastAPI + YOLO + NVIDIA CUDA) nhận H.264 trực tiếp từ **camera điện thoại qua ADB**, bằng **scrcpy-server v4.1** và OpenCV. Không cần mở DroidCam Client, Streamlabs hoặc scrcpy.exe, cũng không cần RTMP/MediaMTX/Tailscale.

## Yêu cầu

- Windows 11, Python 3.11–3.13 (64-bit), điện thoại **Android 12+** nếu muốn lấy camera trực tiếp.
- Cáp USB truyền dữ liệu, bật **Developer options → USB debugging** và chấp nhận “Allow USB debugging” trên điện thoại. Chỉ bật với laptop tin cậy.
- File `adb.exe`, `AdbWinApi.dll`, `AdbWinUsbApi.dll`, `scrcpy-server` ở `tools/adb/` (đã tích hợp từ bộ scrcpy của bạn).
- **Hai model YOLO** bạn đã có, tự chép từ project cũ vào:
  - `models/detection/yolo11s.pt`
  - `models/pose_classification/leeyunjai-falldetect-11x.pt`

**Hai trọng số `.pt` không có trong ZIP nguồn bạn cung cấp nên không được đóng gói.** Thiếu model thì AI không chạy.

## Chạy

1. Giải nén ra thư mục mới. Cắm điện thoại USB, bật USB debugging, đồng ý hộp thoại trên điện thoại. Đóng DroidCam/scrcpy cũ nếu đang chiếm camera.
2. Chạy `START_WINDOWS.bat` lần đầu để tạo `.env`; đặt `FALLGUARD_PASSWORD` ít nhất 12 ký tự; lưu lại.
3. Chỉnh `.env`: `CCTV_URL=adb:back` để dùng camera sau, `adb:front` cho camera trước. Nếu Android **dưới 12**, có thể dùng `adb:display` để chiếu màn hình; khi đó cần mở ứng dụng Camera trên điện thoại (và FallGuard sẽ nhận nội dung toàn màn hình, gồm UI nếu có).
4. Chạy `START_WINDOWS.bat` lại. Lần đầu cài thư viện Python và GPU có thể mất thời gian.
5. Kiểm tra USB bằng `CHECK_ADB_CAMERA.bat`. Nếu báo `[OK] Decoded frame ...`, mở `http://localhost:8000` và đăng nhập để xem CCTV, bật phân tích AI.

**Không chạy đồng thời** `CHECK_ADB_CAMERA.bat` và FallGuard trên cùng cổng ADB (cả hai dùng port 27183). Hãy tắt FallGuard trước khi kiểm tra.

## Cấu hình ADB trong `.env`

| Biến | Mặc định | Ý nghĩa |
|--|--|--|
| `CCTV_URL` | `adb:back` | `adb:back`, `adb:front`, `adb:display` |
| `CCTV_AUTOSTART` | `1` | Tự kết nối điện thoại khi mở FallGuard |
| `ADB_DEVICE_SERIAL` | trống | Chỉ điền nếu có nhiều thiết bị `adb devices` |
| `ADB_STREAM_PORT` | `27183` | Cổng nội bộ chỉ trên máy tính |
| `ADB_MAX_SIZE` | `1280` | Giới hạn kích thước video |
| `ADB_VIDEO_BIT_RATE` | `3000000` | Bitrate H.264 (bps) |
| `ADB_CAMERA_FPS` | `20` | FPS mong muốn của camera |

Telegram vẫn hoạt động qua Gateway nếu bạn cấu hình URL và key; chỉ truyền video là qua USB. Tính năng phát hiện ngã vẫn cần xác nhận liên tục ít nhất 5 giây, không thay thế thiết bị giám sát y tế chuyên dụng.

## Xử lý sự cố

- `unauthorized`: mở khóa màn hình, bấm **Allow USB debugging**, rồi chạy lại.
- `no devices`: kiểm tra cáp data, driver OEM Windows, bật USB debugging, thử File transfer (không bắt buộc nếu ADB nhận).
- `more than one device`: điền `ADB_DEVICE_SERIAL` lấy từ `tools\adb\adb.exe devices`.
- `scrcpy-server exited`: Android 12+ để dùng camera; kiểm tra ứng dụng khác đang sử dụng camera. Thử `adb:display` để loại trừ camera không tương thích.
- Màn hình web có CCTV nhưng AI báo lỗi: chắc chắn đã chép đủ hai `.pt` đúng đường dẫn.
- Mỗi lần thay đổi `.env`, khởi động lại `START_WINDOWS.bat`.

## Kiểm thử

Chạy `python -m pip install pytest httpx` rồi `python -m pytest -q` trong môi trường phù hợp. Các bài test giả lập ADB, không thể chứng minh thiết bị thật sẽ hỗ trợ codec/camera. Cần kiểm tra `CHECK_ADB_CAMERA.bat` trên Windows thực tế.

Mã công cụ ADB/scrcpy được cung cấp từ file `Phone stream.zip` của bạn. Thông tin giấy phép có tại `tools/adb/LICENSE.txt`. Không đăng tải lại ZIP khi chứa thông tin riêng tư trong `.env`.
