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
| `models/fall/best_fall_lstm.pth` | **Đã có trong ZIP**: chính file `best_fall_lstm(2).pth` bạn gửi, đổi tên. Loader đọc scaler NumPy bằng allowlist giới hạn với `weights_only=True`; không thay đổi trọng số. |
| `models/pose/yolo11n-pose.pt` | **Đã có trong ZIP**: chính file `yolo11n-pose(1).pt` bạn gửi, đổi tên. Không cần tải lại model khi chạy bản ZIP này. |

YOLO Pose là model pretrained; BiLSTM là model bạn train. Nếu tải tự động `yolo11n-pose.pt` không thành công, hãy download trọng số chính thức từ [Ultralytics YOLO11 pose](https://docs.ultralytics.com/tasks/pose/), đặt tại `models/pose/yolo11n-pose.pt`, rồi chạy lại. Model **không** tự huấn luyện lại khi khởi động FallGuard.

## Chạy trên Windows

1. Giải nén ZIP mới thành một thư mục riêng, ví dụ `D:\FallGuard_Pose_LSTM`.
2. Cắm điện thoại Android qua USB, bật **USB debugging** (chấp nhận cấp quyền); Android 12+ để dùng `adb:back` hoặc `adb:front`.
3. Chạy `START_WINDOWS.bat`. Nếu chưa có `.env`, chương trình sẽ tạo từ `.env.example` và mở Notepad. Điền mật khẩu `FALLGUARD_PASSWORD` **ít nhất 12 ký tự** và cấu hình Telegram nếu dùng.
4. Chạy `START_WINDOWS.bat` lại. Lần đầu cần Internet để cài thư viện. Hai model đã nằm đúng đường dẫn trong ZIP; nếu clone từ Git thì phải chép lại model theo mục bên dưới.
5. Mở `http://localhost:8000`, đăng nhập, bật camera và **bật phân tích AI** trên dashboard.

**Nâng cấp:** ưu tiên giải nén bản ZIP vào một thư mục mới, chép `.env` từ bản cũ nếu đã cấu hình. Nếu chép đè, xóa test cũ `tests/test_cctv_5s.py` (đã thay bằng `test_cctv_tracking.py`). `START_WINDOWS.bat` dùng dấu phiên bản dependency mới để cài bổ sung PyTorch phù hợp và `lap` cho ByteTrack.

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
python -m pip install -r requirements.txt
python -m pytest -q
```

Bộ test bao gồm: 32-frame window, xác nhận bằng nhiều dự đoán, reset khi camera ngắt, multi-person, đúng công thức 55 feature, checkpoint thật qua PyTorch và Telegram delivery. Có thể chạy không cần Android.

## Cấu trúc

```
fallguard/
    detector.py           # YOLO Pose + BiLSTM + scaler
    checkpoint.py         # loader cho scaler NumPy/Tensor
    cctv.py               # ADB camera + 32-frame tracker
    server.py             # API + alerts
models/
    fall/best_fall_lstm.pth  # checkpoint của bạn (đã đóng gói)
    pose/yolo11n-pose.pt     # đã có trong ZIP, bỏ qua khi commit Git
static/                   # Dashboard hiện có (đã cập nhật trạng thái)
tools/adb/                # Công cụ USB ADB/scrcpy
START_WINDOWS.bat
CHECK_MODELS.bat           # kiểm tra nạp model + suy luận với đầu vào giả lập
CHECK_GPU.bat              # kiểm tra PyTorch CUDA
.env.example
```

**Không đưa file `.env` chứa mật khẩu/Gateway key lên GitHub.** Nếu có nhiều người trong khung hình và thường bị che khuất, có thể cần fine-tune tracking hoặc huấn luyện bổ sung trên video tại môi trường đó.

## Test model mới trên video trước khi kết nối camera

```
.venv\Scripts\python.exe TEST_VIDEO.py "D:\Videos\fall_test.mp4"
```

Lệnh in tiến độ, `P(FALL)` cho từng người và danh sách `FALL ALERT` (nếu có). Thử tối thiểu video té ngã và video nằm/ngồi/cúi để so sánh báo nhầm với model cũ. Script này dùng **duy nhất** YOLO Pose + BiLSTM, không gửi Telegram khi chỉ kiểm tra video.


## Kiểm tra nhanh hai model

Sau khi `START_WINDOWS.bat` đã cài xong môi trường, chạy `CHECK_MODELS.bat`.
Script nạp cả hai file, chạy YOLO trên một khung hình trống và BiLSTM trên
hai chuỗi giả lập `(32, 55)`. Kết quả `[PASS]` xác nhận nạp và suy luận hoạt động;
không phải phép đo độ chính xác nhận diện té ngã. Không cần cắm điện thoại,
không mở server và không gửi Telegram trong bước kiểm tra này.

Nếu cần ép CPU để kiểm tra, mở CMD tại thư mục project:

```bat
set FALL_DEVICE=cpu
.venv\Scripts\python.exe CHECK_MODELS.py
```

## Git và trọng số

`.gitignore` bỏ qua `.env`, model (`.pt`, `.pth`, ...), dữ liệu/video, kết quả
benchmark, file ghi hình, cache, môi trường ảo, log và các file ZIP.
Code, `.env.example`, README, test, manifest benchmark và công cụ ADB vẫn có
thể commit. Model có trong ZIP bàn giao nhưng không được commit vào Git.

Sau khi clone repo, đặt lại hai file:

```text
models/fall/best_fall_lstm.pth
models/pose/yolo11n-pose.pt
```

Kiểm tra trước khi commit:

```bash
git status --short
git ls-files -ci --exclude-standard
```

Lệnh thứ hai liệt kê file đã được Git theo dõi nhưng hiện khớp `.gitignore`.
Thêm `.gitignore` không tự bỏ theo dõi các file đã commit. Với hai model,
có thể bỏ theo dõi mà giữ file trên máy bằng:

```bash
git rm --cached --ignore-unmatch -- models/fall/best_fall_lstm.pth models/pose/yolo11n-pose.pt
```

Nếu danh sách còn model benchmark hoặc `.env`, bỏ theo dõi từng đường dẫn đó
bằng `git rm --cached -- "duong-dan-file"`. Lệnh này không xóa file khỏi các
commit cũ; không tự viết lại lịch sử Git khi cập nhật project.


## Đường dẫn Telegram Gateway trong .env

URL gốc, path và API key đều được cấu hình bên ngoài code:

```dotenv
TELEGRAM_GATEWAY_URL=https://your-bot.vercel.app
TELEGRAM_GATEWAY_PATH=/gateway/v1/notify
TELEGRAM_GATEWAY_KEY=YOUR_EXISTING_GATEWAY_KEY
```

Thay URL và key bằng cấu hình bot của bạn; key cần ít nhất 24 ký tự, không chứa
khoảng trắng. URL chỉ chứa HTTPS origin; PATH bắt đầu bằng một dấu `/`, không
chứa domain, query hoặc fragment. Endpoint gửi cảnh báo = URL + PATH.

**Nếu dùng lại `.env` cũ, phải thêm `TELEGRAM_GATEWAY_PATH=/gateway/v1/notify`.**
Ứng dụng không có path mặc định trong code. Thiếu PATH thì Telegram chưa được
cấu hình; không gửi request. Sau khi sửa `.env`, dừng server và chạy lại
`START_WINDOWS.bat` vì cấu hình được nạp lúc khởi động.

Bot không cần sửa nếu giữ route hiện có `/gateway/v1/notify`: HTTP POST,
header `X-Gateway-Key` và payload cảnh báo/ảnh vẫn giữ nguyên. Nếu đổi PATH,
route bên gateway cũng phải tồn tại với cùng phương thức, xác thực và định dạng
request/response. Chỉ sửa `.env` của FallGuard không tạo route mới trên bot.

File `.env` vẫn được bỏ qua bởi Git; chỉ `.env.example` chứa cấu hình mẫu được
đưa vào source. Bấm gửi thử Telegram trên dashboard sau khi khởi động lại.
