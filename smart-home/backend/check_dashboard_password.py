"""Verify the Smart Home dashboard password without shell-quoting pitfalls."""
import os
import sys
from pathlib import Path

try:
    from dotenv import dotenv_values
except ImportError:
    print('[ERROR] Missing python-dotenv. Run SETUP_VENV.bat to install dependencies.', file=sys.stderr)
    sys.exit(2)

backend_dir = Path(__file__).resolve().parent
env_path = backend_dir / '.env'
if not env_path.is_file():
    print('[ERROR] Missing backend/.env.', file=sys.stderr)
    sys.exit(2)

try:
    config = dotenv_values(env_path)
    password = os.environ.get('DASHBOARD_PASSWORD')
    if password is None:
        password = config.get('DASHBOARD_PASSWORD') or ''
except Exception as exc:
    print(f'[ERROR] Cannot read backend/.env: {exc}', file=sys.stderr)
    sys.exit(2)

if 12 <= len(password) <= 512:
    print('[OK] DASHBOARD_PASSWORD is configured.')
    sys.exit(0)

print('[ERROR] Set DASHBOARD_PASSWORD to 12-512 characters in backend/.env.', file=sys.stderr)
sys.exit(1)
