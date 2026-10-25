# FallGuard — YOLO11 Pose + BiLSTM (Kaggle checkpoint)

Bản này **đã thay hoàn toàn model nhận diện té ngã cũ** bằng model bạn train trên Kaggle. Luồng:

```
Camera Android (USB/ADB, scrcpy) -> OpenCV -> YOLO11n-Pose
  -> ByteTrack / ghép người bằng bounding box
  -> 32 mẫu pose (55 đặc trưng) riêng cho từng người
  -> StandardScaler từ checkpoint -> BiLSTM 2 lớp
  -> P(FALL) -> xác nhận 3 cửa sổ liên tiếp
  -> Dashboard + cảnh báo Telegram Gateway
```

Không dùng `yolo11s.pt` và `leeyunjai-falldetect-11x.pt` nữa. **Model mới chỉ nhận diện té ngã**, không thể chẩn đoán đột quỵ.

## Trọng số model

| Đường dẫn | Cách có được |
|--|--|
| `models/fall/best_fall_lstm.pth` | **Đã được đóng gói** từ checkpoint bạn tải lên, chuyển scaler từ NumPy sang Tensor để tải an toàn (`weights_only=True`). Trọng số và các giá trị scaler không đổi. |
| `models/pose/yolo11n-pose.pt` | **Chưa có trong ZIP:** lần chạy đầu Ultralytics sẽ tự tải trọng số pretrained `yolo11n-pose.pt` (~6MB) nếu có Internet. Có thể tải và chép thủ công đúng đường dẫn để chạy offline. |

YOLO Pose là model pretrained; BiLSTM là model bạn train. Nếu tải tự động `yolo11n-pose.pt` không thành công, hãy download trọng số chính thức từ [Ultralytics YOLO11 pose](https://docs.ultralytics.com/tasks/pose/), đặt tại `models/pose/yolo11n-pose.pt`, rồi chạy lại. Model **không** tự huấn luyện lại khi khởi động FallGuard.

## Chạy trên Windows

1. Giải nén ZIP mới thành một thư mục riêng, ví dụ `D:\FallGuard_Pose_LSTM`.
2. Cắm điện thoại Android qua USB, bật **USB debugging** (chấp nhận cấp quyền); Android 12+ để dùng `adb:back` hoặc `adb:front`.
3. Chạy `START_WINDOWS.bat`. Nếu chưa có `.env`, chương trình sẽ tạo từ `.env.example` và mở Notepad. Điền mật khẩu `FALLGUARD_PASSWORD` **ít nhất 12 ký tự** và cấu hình Telegram nếu dùng.
4. Chạy `START_WINDOWS.bat` lại. Lần đầu cần Internet để cài thư viện; đồng thời tự tải YOLO Pose nếu chưa có file trong `models/pose/`.
5. Mở `http://localhost:8000`, đăng nhập, bật camera và **bật phân tích AI** trên dashboard.

**Lưu ý khi nâng cấp từ thư mục cũ:** nếu chép `.env` đã có sang project mới, hãy đổi `CCTV_FALL_THRESHOLD=0.80`. Biến cũ `0.4` quá thấp với model mới; `CCTV_CONFIRMATIONS=3` có thể giữ nguyên. Không xóa mật khẩu hoặc Telegram Gateway nếu đã cấu hình.

## Cấu hình chính (`.env`)

| Biến | Mặc định | Ý nghĩa |
|--|--|--|
| `CCTV_URL` | `adb:back` | `adb:back`, `adb:front`, `adb:display` |
| `CCTV_AUTOSTART` | `1` | Tự bật camera khi mở server |
| `CCTV_FALL_THRESHOLD` | **`0.80`** | Ngưỡng xác suất lớp FALL của BiLSTM (không còn là YOLO detection confidence) |
| `CCTV_CONFIRMATIONS` | `3` | Số cửa sổ 32-frame liên tiếp đủ ngưỡng trước khi cảnh báo |
| `FALL_DEVICE` | `auto` | CUDA nếu có, nếu không dùng CPU |
| `FALL_TORCH_CUDA_INDEX` | `cu126` | Kho wheel PyTorch CUDA Windows; đổi `cu128` nếu phù hợp driver |
| `ADB_CAMERA_FPS` | `20` | FPS stream camera; pipeline AI xử lý tối đa ~6–7 mẫu/s nếu GPU đủ nhanh |
| `ALERT_COOLDOWN_SECONDS` | `60` | Chống gửi Telegram trùng |

## Luồng quyết định và giới hạn

- Mỗi người có **ID + bộ đệm pose riêng**. YOLO Pose xuất ra 17 keypoints và bounding box. Nếu ByteTrack không trả ID, FallGuard thử ghép bằng vị trí/IoU.
- **Chưa đủ 32 mẫu**: hiển thị "Thu thập pose N/32", chưa gọi BiLSTM để kết luận.
- **Đủ 32 mẫu**: chuẩn hóa đúng 55 đặc trưng bằng `scaler_mean`, `scaler_scale` trong checkpoint. Nếu có quá ít frame nhận được pose, không dự đoán.
- **3 cửa sổ liên tiếp** trên `CCTV_FALL_THRESHOLD`: cảnh báo, lưu sự kiện và gửi Telegram. Một đợt té ngã chỉ báo một lần; khi trở về trạng thái không té ngã đủ 8 cửa sổ mới mở lại một đợt mới.
- Không còn quy tắc **"phát hiện FALL liên tục 5 giây"** của model cũ. Khoảng thời gian thu đủ 32 mẫu vẫn phụ thuộc tốc độ máy/camera (lý tưởng gần 5 giây nếu tốc độ xử lý ~6–7 FPS).
- **Quan trọng:** BiLSTM được train trên **32 frame rải đều trên toàn video**, nhưng camera chạy với **cửa sổ 32 mẫu liên tiếp**. Kết quả 97.28% accuracy trong tập Kaggle **không đảm bảo** accuracy tương tự ở camera thật. Khi đổi góc quay, ánh sáng, khoảng cách, có thể xảy ra báo nhầm/bỏ sót; bắt buộc kiểm tra trên các video ngã và không ngã của chính bạn trước khi coi cảnh báo là đáng tin cậy.
- Model phát hiện *sự kiện nghi té ngã*, không thay thế theo dõi trực tiếp hoặc cấp cứu.

## Kiểm thử

```
python -m pip install pytest httpx
python -m pytest -q
```

Bộ test bao gồm: 32-frame window, xác nhận bằng nhiều dự đoán, reset khi camera ngắt, multi-person, đúng công thức 55 feature, checkpoint thật qua PyTorch và Telegram delivery. Có thể chạy không cần Android.

## Cấu trúc

```
fallguard/
    detector.py           # YOLO Pose + BiLSTM + scaler
    cctv.py               # ADB camera + 32-frame tracker
    server.py             # API + alerts
models/
    fall/best_fall_lstm.pth  # checkpoint của bạn (đã đóng gói)
    pose/yolo11n-pose.pt     # tải tự động lần đầu hoặc chép thủ công
static/                   # Dashboard hiện có (đã cập nhật trạng thái)
tools/adb/                # Công cụ USB ADB/scrcpy
START_WINDOWS.bat
.env.example
```

**Không đưa file `.env` chứa mật khẩu/Gateway key lên GitHub.** Nếu có nhiều người trong khung hình và thường bị che khuất, có thể cần fine-tune tracking hoặc huấn luyện bổ sung trên video tại môi trường đó.

## Ngrok (chay rieng, khong tu khoi dong localhost)

1. Tu chay `START_WINDOWS.bat` de khoi dong FallGuard tai `http://localhost:8000`.
2. Cai ngrok, dang ky va cau hinh authtoken theo huong dan ngrok (chi can mot lan). Dat `ngrok.exe` canh `RUN_NGROK.bat` hoac them ngrok vao PATH.
3. Chay `RUN_NGROK.bat` de mo tunnel cong 8000, hoac `RUN_NGROK.bat 8080` neu da thay doi cong. Script **chi chay ngrok**, khong mo web server va khong mo browser.
4. Sao chep dia chi HTTPS trong cua so ngrok de truy cap tu ben ngoai.

Khi dong server bang Ctrl+C / thoat binh thuong, ung dung se dong camera va goi `adb kill-server`. `START_WINDOWS.bat` cung co buoc cleanup du phong. Lenh nay dung ADB daemon chung tren may tinh, co the anh huong cac ung dung khac dang su dung ADB. Neu tat may dot ngot hoac force-kill terminal, cleanup khong duoc bao dam.

Da bo `TEST_VIDEO.py`; van giu bo unit test trong `tests/` de kiem tra he thong khi can.
