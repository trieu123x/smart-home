"""Validate container configuration, then replace PID 1 with the API process."""
import os
from pathlib import Path
import sys


def main():
    from dotenv import load_dotenv
    # Read the same file as native startup without Compose interpolating password '$' characters.
    load_dotenv('/app/.env', override=False, interpolate=False)
    os.environ.setdefault('TELEGRAM_GATEWAY_PATH', '/gateway/v1/notify')
    password = os.environ.get('DASHBOARD_PASSWORD', '')
    if not 12 <= len(password) <= 512:
        raise SystemExit('Set DASHBOARD_PASSWORD (12-512 characters) in backend/.env, then recreate the containers.')
    if os.environ.get('FALL_ENABLED', 'true').lower() not in ('false', '0', 'no'):
        assets = Path(os.environ.get('FALL_ASSETS_DIR', '/app'))
        for relative in ('models/pose/yolo11n-pose.pt', 'models/fall/best_fall_lstm.pth', 'tools/adb/scrcpy-server'):
            if not (assets / relative).is_file():
                raise SystemExit(f'Missing Fall Detection asset: {relative}. Check the Compose mounts.')
    os.execv(sys.executable, [sys.executable, '-m', 'uvicorn', 'app.main:app',
                            '--host', '0.0.0.0', '--port', '8000', '--workers', '1'])


if __name__ == '__main__':
    main()
