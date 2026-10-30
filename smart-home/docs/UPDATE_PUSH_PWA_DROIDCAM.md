# Cap nhat Smart Home: Push tren Topbar, cai PWA va DroidCam

Ban nay duoc tao tu ban **Hybrid Windows** (backend FastAPI chay bang `backend/.venv`, Next.js bang Docker, HTTPS qua ngrok), bao gom cac ban va loi PowerShell/ngrok gan nhat.

## 1. Cac thay doi

- Thanh cong cu chung cua moi trang (Tong quan, Thiet bi, Tu dong hoa, Canh bao) co nut **Thong bao**. Nhan de bat/tat Push va gui thu.
- Nut **Cai ung dung** hien huong dan them vao man hinh chinh; tren Chrome Android se su dung prompt cai dat neu trinh duyet cung cap.
- Trang **Tong quan** hien **hai luong camera doc lap**: `Camera USB - ADB` va `Camera Wi-Fi - DroidCam`. Moi luong co Bat/Tat. AI chi phan tich **mot luong duoc chon** de khong tang doi tai GPU; co the doi nguon AI ngay tren giao dien. Luong con lai van xem truc tiep.
- DroidCam: nhap IP dien thoai va port, nhan **Ket noi**. Khong can sua firmware ESP32, khong can cai DroidCam Client tren Windows neu dung luong MJPEG qua Wi-Fi.

## 2. Cap nhat code

1. Sao luu project va du lieu `backend/smarthome.db` neu dang su dung.
2. Giai nen ban **patch** vao thu muc cha chua `smart-home`, giu nguyen `.env`, `.venv`, models va database. Neu dung ban full, sao luu/copy cac tep private va model cua ban sang ban moi; ban full **khong** bao gom cac tep private nay.
3. Dong cua so FastAPI cu / dung tien trinh dang chiem cong `8000`. Neu backend cu van chay, `START_SMART_HOME.bat` co the bo qua buoc khoi dong lai va ban se nhan loi API 404 voi endpoint DroidCam.
4. Tai thu muc project tren PowerShell:

```powershell
cd D:\smart-home\smart-home
# Chay lai FastAPI va dashboard neu truoc do da dung
.\START_SMART_HOME.bat
# Build lai Next.js do thay doi giao dien
.\BUILD_FRONTEND.bat
# Truy cap HTTPS cho dien thoai
.\START_NGROK.bat
```

Khi dung Docker Compose truc tiep, co the thay `BUILD_FRONTEND.bat` bang:

```powershell
docker compose up -d --build dashboard
```

Khong can tao lai venv hay cai them thu vien Python, vi project da dung `opencv-python` cho AI. Neu OpenCV chua duoc cai, cai theo huong dan model AI hien tai.

## 3. Ket noi DroidCam qua Wi-Fi

1. Cai **DroidCam** cua Dev47Apps tren dien thoai. Bat Wi-Fi, cho dien thoai va may Windows chay FastAPI cung mang LAN.
2. Mo app DroidCam, cap quyen camera va xem **WiFi IP** + **Port** (mac dinh 4747). Bat video tren app.
3. Thu trong trinh duyet **tren Windows**: `http://192.168.1.20:4747/video` (thay IP bang IP app hien thi). Neu khong thay video thi kiem tra firewall/mang/app truoc khi thao tac tren dashboard.
4. Truy cap Smart Home → Tong quan → **Camera Wi-Fi - DroidCam**. Nhap `192.168.1.20`, port `4747`, nhan **Ket noi**. He thong se mo luong MJPEG bang OpenCV backend va hien tren dashboard qua API da xac thuc.
5. De phan tich nga tu DroidCam, nhan **Chon cho AI** o khung DroidCam va bat **Phan tich AI**. Co the chuyen nguoc sang ADB bat cu luc nao.

Chi chap nhan IP IPv4 noi bo (`10.x.x.x`, `172.16-31.x.x`, `192.168.x.x`), khong chap nhan domain/IP cong khai/URL tuy y. Luong camera chi duoc lay boi backend Windows, **khong** duoc mo truc tiep qua ngrok. IP nhap tren UI chi duoc luu trong bo nho den khi backend restart.

De tu ket noi lai sau khi restart backend, them vao `backend/.env` (khong commit `.env`):

```dotenv
DROIDCAM_URL=http://192.168.1.20:4747/video
DROIDCAM_AUTOSTART=1
```

Luu y: neu Android khong cho hai ung dung chiem camera mot luc, can dung **hai dien thoai** de xem ADB va DroidCam dong thoi; hoac dung ADB chieu man hinh thay vi camera voi `CCTV_URL=adb:display`.

## 4. Push va cai web nhu ung dung

- Moi trang co nut **Thong bao**. Nhan de mo menu, sau do nhan **Bat thong bao**; can cap quyen khi trinh duyet hoi. Neu da bat, co the **Gui thong bao thu**.
- **Android Chrome:** nhan **Cai ung dung**. Neu co prompt cai PWA, chap nhan; neu khong, menu Chrome `⋮` → `Cai dat ung dung` / `Them vao man hinh chinh`.
- **iPhone (iOS 16.4+):** mo HTTPS bang Safari, Share/Chia se → Add to Home Screen/Them vao man hinh chinh, mo web app tu bieu tuong roi nhan **Bat thong bao**. iOS khong ho tro website tu cai bang nut bam nhu tren Android.
- Web Push can HTTPS, service worker va VAPID trong `backend/.env`. Neu thay doi dia chi ngrok, PWA/subscription cu co the phai dang ky lai tren dia chi moi.
- Dien thoai co the hoan/thieu thong bao neu bi han che boi he dieu hanh/nguoi dung tat quyen. Khong dung Web Push lam kenh canh bao an toan duy nhat.

## 5. API moi va luu y

- `GET /api/fall/view`: tra ve them `camera.cameras.adb`, `camera.cameras.droidcam`, `camera.analysis_source`.
- `GET /api/fall/frame?source=adb|droidcam&seq=-1`: anh JPG tung nguon.
- `POST /api/fall/droidcam/connect` voi JSON `{"host":"192.168.1.20", "port":4747}`.
- `POST /api/fall/source` voi JSON `{"source":"droidcam"}` hoac `{"source":"adb"}`.
- `POST /api/fall/start?source=droidcam` va `/stop?source=droidcam`.

Tat ca API van yeu cau dang nhap dashboard va bao ve origin cho yeu cau thay doi. Giao dien chi gui ket qua preview thong qua API backend, khong nhung URL camera noi bo vao trang web public.

## 6. Kiem tra loi

- **Camera DroidCam khong hien:** IP/port sai, khac Wi-Fi, mang client isolation, Windows firewall, app DroidCam dang dung app camera khac, stream chua bat. Thu URL `/video` tren Windows.
- **API DroidCam 404:** backend FastAPI cu van chay; restart backend bang venv.
- **Giao dien van cu:** build lai frontend Docker va tai trang Ctrl+Shift+R (tren mobile co the can dong/mo PWA).
- **iPhone khong co bat Push:** mo tu bieu tuong PWA, khong phai tab Safari; phai co HTTPS va cau hinh VAPID.
- **DroidCam den cham:** thu Wi-Fi 5GHz, giam do phan giai trong app, xem tai GPU va so ket noi MJPEG.

### Kiem thu thuc hien trong moi truong tao ban va

- 4 unittest cho validate IP, doi stream, preview JPEG hai nguon, va reset khi doi nguon AI: **dat**.
- Python `compileall` va TypeScript transpile syntactic: **dat**.
- Chua the chay toan bo FastAPI integration tests / Next.js build do moi truong khong co cac package `paho-mqtt`, `pywebpush` va npm package, khong co ket noi cai goi.
- Chua the kiem thu DroidCam, ADB, CUDA, ngrok hoac Push tren dien thoai that.
