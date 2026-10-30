> **Legacy all-in-Docker instructions:** The default `docker-compose.yml` now runs only the dashboard. For the new Windows hybrid venv + Docker architecture, read [HYBRID_WINDOWS.md](HYBRID_WINDOWS.md). Commands in this older guide for the Docker Python backend no longer apply to the default compose file.

# Smart Home + Fall Detection in Docker

`docker-compose.yml` starts the dashboard and the Python backend with the integrated
YOLO Pose/BiLSTM pipeline. Python and Node.js are installed inside the images;
inference uses an NVIDIA GPU through CUDA 12.8. The Windows host needs an
NVIDIA GPU with a current driver and Docker Desktop using the WSL 2 backend.
ESP32 firmware remains on the board. The existing MQTT broker and Telegram Gateway
are configured through `backend/.env`.

## First start

Run commands in the `smart-home/` directory containing `docker-compose.yml`.

1. Keep your existing `backend/.env`. For a fresh clone, copy `backend/.env.example`
   to `backend/.env` and set `DASHBOARD_PASSWORD` to a private password of 12-512
   characters. MQTT and Telegram values are read from this same file.
2. Ensure the local model/tool assets are present:

   ```text
   backend/models/pose/yolo11n-pose.pt
   backend/models/fall/best_fall_lstm.pth
   backend/tools/adb/scrcpy-server
   backend/tools/adb/adb.exe          # Windows camera bridge only
   ```

3. Start the application:

   ```powershell
   docker compose up -d --build
   ```

4. Open **http://localhost:3000** and log in with `DASHBOARD_PASSWORD`.

The first build downloads Python/Node images and the AI libraries. The dashboard
waits for the backend health check before starting. A missing password or asset
produces an explicit error in `docker compose logs backend`.

## Android USB camera on Windows

Docker Desktop does not directly expose the Windows USB phone to the Linux
container. Before enabling the camera, run this in a separate PowerShell terminal:

```powershell
.\START_CAMERA_DOCKER.bat
```

Connect the phone, enable USB debugging and accept its authorization prompt. Keep
the bridge terminal open. Stop the experimental/native camera process before
using the same phone in Docker. Then use **Bật camera** and **Phân tích AI** in
the shared dashboard.

The helper stops the default ADB server on 5037 to release USB ownership before
starting the dedicated bridge. Other ADB sessions using that default server will
disconnect; close the native/experimental camera application first.

The Windows ADB server listens on port **5038**, separate from the usual 5037.
The container uses Linux ADB to connect to `host.docker.internal:5038`; the raw
H264 forward is read at `host.docker.internal:27183`. Allow these two TCP ports
through Windows Firewall only for the Docker/WSL network. The ADB server is a
device-control endpoint without application authentication; do not forward these
ports from a router or expose them publicly. Ctrl+C stops the bridge.

Reference: [Docker Desktop host networking names](https://docs.docker.com/desktop/features/networking/),
[ADB listener behavior](https://android.googlesource.com/platform/packages/modules/adb/+/27282a72e35940a502932fa4c57eb5cff59e0b94/socket_spec.cpp).

The application still starts if the phone/bridge is unavailable and reports the
camera connection state. Set `CCTV_AUTOSTART=0` in `backend/.env` to start it only
when the dashboard button is pressed.

## Data and configuration

- SQLite data is stored in the named volume `smarthome_data` at `/data/smarthome.db`.
- Model weights and `scrcpy-server` are mounted read-only. They are not baked into
  the image. The `.env` file is also mounted read-only and excluded from builds.
- Only dashboard port 3000 is published. API and WebSocket traffic pass through
  the dashboard to the backend on the private Compose network.
- Docker starts with a separate database volume. An existing native
  `backend/smarthome.db` is not overwritten or automatically imported.
- The backend image installs PyTorch 2.7.1 and torchvision 0.22.1 with CUDA 12.8
  libraries. Compose reserves one NVIDIA GPU and sets `FALL_DEVICE=cuda:0`,
  overriding any `FALL_DEVICE` value in `backend/.env`. If CUDA is unavailable,
  the AI reports an error instead of silently running on CPU.
- After switching from the previous CPU image, rebuild and recreate the backend:

  ```powershell
  docker compose up -d --build
  ```

References: [PyTorch CUDA wheels](https://pytorch.org/get-started/previous-versions/),
[Compose GPU reservation](https://docs.docker.com/compose/how-tos/gpu-support/),
[Docker Desktop GPU requirements](https://docs.docker.com/desktop/features/gpu/).

After changing `backend/.env`, recreate the services to load the new settings:

```powershell
docker compose up -d --force-recreate
```

For Compose-level options, use a `.env` beside `docker-compose.yml`, for example:

```dotenv
DASHBOARD_PORT=3001
ADB_SERVER_HOST=host.docker.internal
ADB_SERVER_PORT=5038
ADB_STREAM_HOST=host.docker.internal
ADB_STREAM_PORT=27183
```

The bridge script uses 5038 by default; if changing that port, start ADB manually
with the matching `-P` value. If the dashboard port is changed, browse the new port.

## Useful commands

```powershell
docker compose ps
docker compose logs -f
docker compose down
```

`docker compose down` preserves the database volume. `docker compose down -v`
deletes it; use that only when intentionally resetting Docker data.

To back up the Docker database consistently without stopping it:

```powershell
docker compose exec backend python -c "import sqlite3; source=sqlite3.connect('/data/smarthome.db'); target=sqlite3.connect('/data/backup.db'); source.backup(target); target.close(); source.close()"
docker compose cp backend:/data/backup.db ./smarthome-backup.db
```

## Validation

The previous CPU configuration was validated with Docker Desktop Linux containers
on Windows. The current CUDA configuration has not been built or run, as requested.
Results below apply to the previous CPU configuration:

- Both images built successfully and both services passed their health checks.
- Login, logout, protected APIs and authenticated WebSocket event delivery worked
  through the dashboard port.
- The actual YOLO Pose and BiLSTM weights loaded on CPU and completed inference
  on synthetic inputs. This checks runtime compatibility, not detection accuracy.
- An ingested event survived a backend restart and could be acknowledged afterward.
- All 18 backend tests passed, including native and remote ADB routing.

The Docker test used an isolated database with MQTT and Telegram disabled. A
physical Android camera, ESP32 and external notifications still require testing
with your connected devices and service credentials.
