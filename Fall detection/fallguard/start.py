"""Start once on the computer hosting the model. Keep this terminal open."""
import os
import subprocess
from pathlib import Path
import threading
import time
import urllib.request
import webbrowser

os.environ.setdefault('YOLO_AUTOINSTALL', 'false')

if __name__ == '__main__':
    import uvicorn
    port = int(os.getenv('PORT', '8000'))
    url = f'http://localhost:{port}'
    print('\n=== FALLGUARD - NHAN DIEN TE NGA ===', flush=True)
    print(f'Mo tren may tinh: {url}', flush=True)
    print('Giu cua so nay mo. Doi model nap xong tren trang web.\n', flush=True)
    def open_when_ready():
        for _ in range(60):
            try:
                urllib.request.urlopen(url, timeout=1).close()
                webbrowser.open(url)
                return
            except Exception:
                time.sleep(1)
    if os.getenv('FALL_NO_BROWSER') != '1':
        threading.Thread(target=open_when_ready, daemon=True).start()
    try:
        uvicorn.run('server:app', host='127.0.0.1', port=port, workers=1, ws_max_size=1_000_000)
    finally:
        # Stop the bundled ADB daemon when the local server exits.
        adb = Path(__file__).resolve().parent.parent / 'tools' / 'adb' / 'adb.exe'
        if adb.is_file():
            try:
                subprocess.run([str(adb), 'kill-server'], timeout=8,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                print('[ADB] Da dung ADB server.', flush=True)
            except (OSError, subprocess.TimeoutExpired):
                print('[ADB] Khong the dung ADB server tu dong.', flush=True)
