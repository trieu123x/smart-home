"""Start once on the computer hosting the model. Keep this terminal open."""
import os
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
    uvicorn.run('server:app', host='127.0.0.1', port=port, workers=1, ws_max_size=1_000_000)
