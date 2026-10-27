"""Bootstrap and run the unified dashboard. Ctrl+C stops both child processes."""
import getpass
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / 'backend'
FRONTEND = ROOT / 'frontend'
LEGACY = ROOT.parent / 'Fall detection'


def run(command, cwd):
    subprocess.run(command, cwd=cwd, check=True)


def main():
    npm = shutil.which('npm.cmd') or shutil.which('npm')
    node = shutil.which('node')
    if not npm or not node:
        raise SystemExit('Install Node.js 20 or 22 LTS (including npm), then restart the terminal.')
    env_path = BACKEND / '.env'
    if not env_path.exists():
        # Reuse camera and gateway configuration without copying credentials into source.
        from_config = LEGACY / '.env'
        env_path.write_text(from_config.read_text(encoding='utf-8-sig') if from_config.exists() else '', encoding='utf-8')
    from dotenv import dotenv_values, set_key
    values = dotenv_values(env_path)
    # The old Smart Home sender used this fixed gateway path.
    if not values.get('TELEGRAM_GATEWAY_PATH'):
        set_key(env_path, 'TELEGRAM_GATEWAY_PATH', '/gateway/v1/notify')
    password = os.environ.get('DASHBOARD_PASSWORD', values.get('DASHBOARD_PASSWORD') or values.get('FALLGUARD_PASSWORD') or '')
    if not 12 <= len(password) <= 512:
        password = getpass.getpass('Set dashboard password (at least 12 characters): ')
        if not 12 <= len(password) <= 512 or '\n' in password or '\r' in password:
            raise SystemExit('Password must contain at least 12 characters and no newlines.')
    if not values.get('DASHBOARD_PASSWORD') and not os.environ.get('DASHBOARD_PASSWORD'):
        set_key(env_path, 'DASHBOARD_PASSWORD', password)
    # Migrate local model/tool assets once. The integrated runtime has no legacy imports.
    for name in ('models', 'tools'):
        source = LEGACY / name
        destination = BACKEND / name
        if source.is_dir():
            for item in source.rglob('*'):
                if item.is_file():
                    target = destination / item.relative_to(source)
                    if not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, target)
    for file in (BACKEND / 'models/pose/yolo11n-pose.pt', BACKEND / 'models/fall/best_fall_lstm.pth'):
        if not file.is_file():
            raise SystemExit(f'Missing model: {file}. Copy the trained weights before starting.')
    dependency_files = [BACKEND / 'requirements.txt', BACKEND / 'requirements-fall.txt']
    signature = hashlib.sha256(b''.join(path.read_bytes() for path in dependency_files)).hexdigest()
    marker = BACKEND / '.venv' / '.dashboard-dependencies'
    if not marker.exists() or marker.read_text() != signature:
        run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements-fall.txt'], BACKEND)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(signature)
    # Always rebuild so source changes and proxy configuration take effect.
    run([npm, 'ci'], FRONTEND)
    run([npm, 'run', 'build'], FRONTEND)
    backend_env = {**os.environ, 'DASHBOARD_PASSWORD': password, 'YOLO_AUTOINSTALL': 'false'}
    processes = []
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        processes.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], cwd=BACKEND, env=backend_env, creationflags=flags))
        processes.append(subprocess.Popen([node, 'node_modules/next/dist/bin/next', 'start', '--hostname', '0.0.0.0', '--port', '3000'], cwd=FRONTEND, creationflags=flags))
        def open_browser():
            for _ in range(90):
                if any(process.poll() is not None for process in processes):
                    return
                try:
                    urllib.request.urlopen('http://localhost:3000/api/health', timeout=1).close()
                    webbrowser.open('http://localhost:3000')
                    return
                except OSError:
                    time.sleep(1)
        threading.Thread(target=open_browser, daemon=True).start()
        print('Dashboard: http://localhost:3000 — Ctrl+C to stop.', flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(.5)
        raise SystemExit('A dashboard process stopped. Review the output above.')
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == '__main__':
    # Only the small bootstrap dependencies are needed before configuration is loaded.
    try:
        import dotenv
    except ImportError:
        run([sys.executable, '-m', 'pip', 'install', 'python-dotenv==1.0.1'], BACKEND)
    main()
