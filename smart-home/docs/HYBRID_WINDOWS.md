# Smart Home - Huong dan chay Hybrid: Windows Python venv + Docker + Ngrok

> Phien ban nay da duoc doi sang **backend FastAPI + AI + MQTT + SQLite + Web Push chay trong Python venv tren Windows** va **chi frontend Next.js build/chay trong Docker**. Khong can build Docker image PyTorch/CUDA. De tu dong khoi dong backend, dashboard va ngrok, su dung `START_NGROK.bat`.

## 1. Kien truc va luong du lieu

```text
ESP32 --MQTT--> Python FastAPI (Windows, backend/.venv, port 8000)
Android USB Camera --ADB --> FallGuard (Windows, CUDA / CPU)
                             | SQLite: backend/smarthome.db
                             | Web Push (VAPID), Telegram, WebSocket
                             v
                    Docker Desktop / Next.js (port 3000)
                             |  /api/* -> http://host.docker.internal:8000/api/*
                             |  /ws    -> http://host.docker.internal:8000/ws
                             v
                     Ngrok HTTPS -> port 3000
                             v
                   Trinh duyet Android + iPhone
```

**Luu y:** `host.docker.internal` chi la ten mien noi bo de Next.js trong Docker truy cap Python backend dang chay tren host Windows. Frontend khong goi API truc tiep tu trinh duyet, do do khong can public cong 8000. Dashboard duoc bind vao `127.0.0.1:3000`; ngrok chi tunnel 3000.

## 2. Cau truc thu muc

```text
smart-home/
|-- SETUP_VENV.bat           # Tao backend/.venv + cai dependencies
|-- START_BACKEND_VENV.bat   # FastAPI + AI + MQTT + Web Push (Windows)
|-- START_SMART_HOME.bat     # Tu khoi dong backend Windows + Next.js Docker
|-- BUILD_FRONTEND.bat      # Build lai CHI frontend Docker
|-- START_NGROK.bat         # Khoi dong hybrid + ngrok HTTPS
|-- MIGRATE_DOCKER_DB.bat    # Chuyen SQLite tu Docker volume cu (1 lan)
|-- START_DASHBOARD.bat      # Alias cua START_SMART_HOME.bat
|-- docker-compose.yml      # Chi con service dashboard
|-- Dockerfile              # Chi build Next.js
|-- backend/
|   |-- .venv/              # Tu tao, KHONG commit Git
|   |-- .env                # Tu tao va cau hinh, KHONG commit Git
|   |-- smarthome.db        # SQLite, KHONG commit Git
|   |-- models/pose/yolo11n-pose.pt  # Can copy model that
|   |-- models/fall/best_fall_lstm.pth
|   |-- tools/adb/          # adb.exe, DLLs va scrcpy-server
|   `-- app/                # FastAPI, MQTT, Web Push
`-- frontend/               # Next.js + PWA
```

## 3. Yeu cau may Windows

- Windows 10/11, Docker Desktop (WSL2), Docker Compose v2; **bat Docker Desktop truoc khi chay**.
- Python **3.13**, duoc cai bang Python.org va `py -3.13` hoat dong.
- Internet de `pip` cai thu vien va Docker download `node:22-bookworm-slim` lan dau.
- NVIDIA GPU la tuy chon; dung GPU neu da cai driver tuong thich CUDA 12.8. Neu khong co GPU, AI co the chay CPU (cham hon).
- `ngrok.exe` trong thu muc `smart-home/` hoac tren PATH; phai cau hinh authtoken.
- Android ket noi USB, bat USB debugging neu dung camera ADB; iPhone chi dung de nhan Web Push, khong can ADB.

## 4. Chuyen tu ban Docker cu: sao luu database TRUOC khi cap nhat

**Neu ban dang dung ban full-Docker**, SQLite cu duoc luu trong Docker volume ten mac dinh `smarthome_data`. Khi doi sang venv, duong dan DB se thanh `backend/smarthome.db`. Hai noi luu tru KHAC NHAU. Khong duoc xoa volume cu truoc khi chuyen.

1. **Truoc khi thay cac file cu**, trong project ban cu: `docker compose stop backend` (neu can, stop dashboard nua). Dung `docker ps` de kiem tra backend da dung.
2. Sao chep patch/hybrid vao project, giu nguyen file `.env`, model, DB hien tai.
3. Neu **chua co** `backend/smarthome.db`, chay `MIGRATE_DOCKER_DB.bat`. Script chi doc volume `smarthome_data` va copy SQLite ra `backend/smarthome.db`; khong ghi de DB hien co.
4. Kiem tra database da co, roi moi chay `START_SMART_HOME.bat`.

Neu ten volume khac (kiem tra `docker volume ls`), can sao chep tu volume dung; script mac dinh chi nhan `smarthome_data`. Neu truoc do da chay backend Python native va co DB trong `backend/`, **khong chay migration**. Tuyet doi khong dung `docker compose down -v` neu muon giu du lieu.

## 5. Chay lan dau

### Buoc 1: Giai nen va chuyen thu muc

```powershell
cd D:\smart-home
```

Thay `D:\smart-home` bang thu muc thuc te. Neu ban dang cap nhat tu phien ban cu, **giu lai** `backend/.env`, `backend/models/`, `backend/tools/`, `backend/smarthome.db` neu da co.

### Buoc 2: Tao venv va cai Python dependencies

Neu muon dung GPU NVIDIA va driver phu hop CUDA 12.8:

```powershell
.\SETUP_VENV.bat --cuda
```

Neu khong co NVIDIA GPU (hoac can chay CPU):

```powershell
.\SETUP_VENV.bat
```

Script tao `backend\.venv`, cai FastAPI, Ultralytics, OpenCV, PyTorch, Web Push va cac thu vien AI. Cuoi script se in `CUDA available: True/False`. `False` co the la chua co driver/PyTorch CUDA tuong thich, khong dong nghia model khong chay duoc CPU. Neu muon kiem tra lai:

```powershell
.\backend\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

Chi phai cai lai neu xoa `.venv` hoac cap nhat danh sach dependencies. Docker **khong** cai torch.

### Buoc 3: Cau hinh backend/.env

`SETUP_VENV.bat` tu copy `backend/.env.example` thanh `backend/.env` khi file chua ton tai. Mo file va dien it nhat:

```dotenv
DATABASE_URL=sqlite:///./smarthome.db
DASHBOARD_PASSWORD=mot_mat_khau_rieng_it_nhat_12_ky_tu
FALL_ENABLED=true
FALL_DEVICE=auto
CCTV_URL=adb:back
CCTV_AUTOSTART=1
MQTT_ENABLED=true
MQTT_HOST=broker.hivemq.com
MQTT_PORT=1883
MQTT_PREFIX=ptit_sh_k7x2q9/home/
```

`MQTT_PREFIX` phai trung voi firmware ESP32. Neu chua co model AI hoac chua su dung camera, co the dat `FALL_ENABLED=false` tam thoi (IoT/MQTT va Web Push van hoat dong). Dung broker MQTT rieng co user/pass thay vi broker public khi su dung thuc te.

**Giữ nguyên VAPID keys** cu neu da co thiet bi dang ky Push. Neu chua co:

```powershell
cd backend
.\.venv\Scripts\python.exe generate_vapid.py
cd ..
```

Chep `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` vao `backend/.env`. Khong commit private key hoac password. Doi VAPID keys se lam cac thiet bi cu phai dang ky Push lai.

### Buoc 4: Dat model va ADB assets

- Dat `yolo11n-pose.pt` vao `backend/models/pose/`.
- Dat `best_fall_lstm.pth` vao `backend/models/fall/`.
- Dung bo cong cu trong `backend/tools/adb/` (bao gom `adb.exe`, `AdbWinApi.dll`, `AdbWinUsbApi.dll`, `scrcpy-server`).
- Trong `.env`, **xoa** `ADB_SERVER_HOST`, `ADB_SERVER_PORT`, `ADB_STREAM_HOST`, `ADB_STREAM_PORT` neu truoc do chi khai bao de bridge camera Docker; mac dinh Windows dung localhost / ADB port 5037.
- Cam Android USB: bat Developer options, USB debugging, chap nhan hop thoai tren dien thoai.

Thu camera:

```powershell
.\backend\tools\adb\adb.exe devices
```

Dau ra can co trang thai `device`; neu la `unauthorized` thi kiem tra dien thoai. Trong hybrid **khong chay** `START_CAMERA_DOCKER.bat`.

### Buoc 5: Khoi dong backend Windows va frontend Docker

```powershell
.\START_SMART_HOME.bat
```

Script se:

1. Xac nhan Docker Desktop va venv co san.
2. Neu FastAPI chua chay, mo cua so `Smart Home Backend (venv)` (host `0.0.0.0:8000` de Docker Desktop truy cap).
3. Doi `http://127.0.0.1:8000/api/health` tra loi.
4. Neu Docker image frontend chua ton tai, build Next.js; neu co roi thi khoi dong lai khong rebuild.
5. Kiem tra `http://127.0.0.1:3000/api/health`; in thong bao thanh cong.

Mo `http://localhost:3000` va dang nhap bang `DASHBOARD_PASSWORD`.

Kiem tra rieng:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:3000/api/health
docker compose ps
docker compose logs -f dashboard
```

`docker compose ps` **chi co dashboard**, khong con service/backend AI trong Docker.

### Buoc 6: Bat ngrok de dien thoai truy cap qua HTTPS

Cau hinh token mot lan:

```powershell
ngrok config add-authtoken YOUR_TOKEN
```

Neu `ngrok.exe` nam trong thu muc project, co the dung `.\ngrok.exe config add-authtoken YOUR_TOKEN`.

Chay:

```powershell
.\START_NGROK.bat
```

Script goi `START_SMART_HOME.bat` truoc, kiem tra mat khau dashboard da cai, sau do mo ngrok HTTP tunnel toi **DUY NHAT cong 3000**. Copy dia chi `https://...ngrok-free.app` va mo tren dien thoai. Khong mo tunnel toi 8000, 5037, 5038 hoac 27183.

**Android:** mo website HTTPS trong Chrome, dang nhap, vao Cảnh báo, nhan `Bật thông báo`, cho phep, roi `Gửi thử`.

**iPhone (iOS 16.4+):** mo HTTPS bang Safari, Share -> Add to Home Screen, mo tu icon Home Screen, dang nhap, vao Cảnh báo, nhan `Bật thông báo` va cho phep. Neu ngrok tao domain moi, can mo URL moi va dang ky nhan Push lai; tren iPhone co the can them lai icon man hinh chinh.

## 6. Nhung lan sau chi can chay gi?

- **Chay dashboard local:** `START_SMART_HOME.bat`.
- **Chay va public HTTPS ngrok:** `START_NGROK.bat` (goi tu dong startup hybrid).
- **Sua frontend / PWA / Next.js:** `BUILD_FRONTEND.bat` de build lai CHI Next.js Docker image; khong cai lai Python.
- **Sua backend Python:** dung cua so `Smart Home Backend (venv)` bang Ctrl+C, mo lai `START_BACKEND_VENV.bat` (hoac `START_SMART_HOME.bat` khi backend da dung).
- **Sua file requirements:** chay lai `SETUP_VENV.bat` (co `--cuda` neu muon cac wheel CUDA).
- **Thay .env backend:** restart backend venv.

Dung ngrok: Ctrl+C trong cua so ngrok. Dung backend: Ctrl+C trong cua so backend. Dung dashboard:

```powershell
docker compose stop dashboard
```

Khong su dung `docker compose down -v` de don dep neu con DB Docker cu can sao luu.

## 7. Bao mat va luu y van hanh

- Uvicorn bind `0.0.0.0:8000` de Docker Desktop truy cap host. **Kiem tra Windows Defender Firewall va han che inbound TCP 8000 tu LAN/Internet** theo cau hinh mang cua ban; khong forward cong 8000 tren router. Neu Docker khong ket noi backend, kiem tra firewall thay vi tat toan bo firewall.
- Chi tunnel dashboard port 3000 qua ngrok, su dung mat khau >=12 ky tu va HTTPS.
- `backend/.env` chua mat khau, VAPID private key, Telegram, MQTT; khong commit.
- `backend/smarthome.db` chua lich su, subscriptions Push; sao luu file nay khi backend da dung. Docker container frontend khong chua SQLite.
- Domain ngrok mien phi co the thay doi. Browser Push la best-effort, khong thay the coi bao dong/Telegram cho su kien nguy hiem.
- Backend phai dang chay thi ESP32, AI va thong bao canh bao moi hoat dong; ngrok chi la cong bo website ra internet.

## 8. Xu ly loi thuong gap

| Trieu chung | Cach xu ly |
|---|---|
| `Run SETUP_VENV.bat first` | Tao venv va cai thu vien tu `SETUP_VENV.bat` |
| `Python 3.13 is required` | Cai Python 3.13, kiem tra `py -3.13 --version` |
| `dashboard password` chua cau hinh | Dat `DASHBOARD_PASSWORD` trong `backend/.env`; restart backend |
| AI khong chay / thieu model | Kiem tra 2 file trong `backend/models`; thu `FALL_ENABLED=false` de chay IoT truoc |
| CUDA False | Kiem tra driver NVIDIA, thu `SETUP_VENV.bat --cuda`, kiem tra PyTorch CUDA |
| ADB `unauthorized` | Bat USB debugging, cho phep thiet bi; `backend\tools\adb\adb.exe devices` |
| `Docker daemon is not running` | Mo Docker Desktop, cho WSL2 khoi dong |
| Frontend 502/503 khi goi `/api` | Kiem tra FastAPI port 8000 va ket noi `host.docker.internal:8000` tu Docker; kiem tra firewall |
| Dashboard vao duoc, API health loi | Khoi dong backend; kiem tra `docker compose logs dashboard` |
| Old Docker backend is still running | Dung container cu; migrate DB neu can; sau do chay lai hybrid |
| iPhone khong co Push | iOS 16.4+, Add to Home Screen, mo tu icon, cap quyen, dung URL HTTPS |
| Khoi dong ngrok bao thieu token | `ngrok config add-authtoken YOUR_TOKEN` |
| Lich su bi trong sau khi doi Docker -> venv | Kiem tra `backend/smarthome.db`; neu chua co, dung backend va `MIGRATE_DOCKER_DB.bat` |

**Kiem tra nhanh:** `http://localhost:3000` -> dashboard; `http://127.0.0.1:8000/api/health` -> FastAPI. Ket qua dung: Docker dashboard, Python backend ngoai Docker, ngrok cong 3000, Web Push/Telegram/ESP32/AI van duoc xu ly tai backend Windows.
