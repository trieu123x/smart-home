"""Load Telegram settings from environment or the .env in the project root.

No credentials belong in this file. Supports simple KEY=value lines,
optional matching quotes, blank lines and full-line # comments.
Values are literal: no shell execution, interpolation or inline comments.
"""
import os
from pathlib import Path


def _read_env(path):
    values = {}
    if not path.is_file():
        return values
    for number, raw in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        if not separator:
            raise ValueError(f'.env: dòng {number} cần có dạng KEY=value.')
        value = value.strip()
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f'.env: dòng {number} chưa đóng dấu nháy.')
            value = value[1:-1]
        values[key.strip()] = value
    return values


_settings = _read_env(Path(__file__).resolve().parent.parent / '.env')
# Process environment takes precedence, including an explicitly empty value.
GATEWAY_URL = os.environ.get('TELEGRAM_GATEWAY_URL', _settings.get('TELEGRAM_GATEWAY_URL', '')).strip()
GATEWAY_PATH = os.environ.get('TELEGRAM_GATEWAY_PATH', _settings.get('TELEGRAM_GATEWAY_PATH', '')).strip()
GATEWAY_API_KEY = os.environ.get('TELEGRAM_GATEWAY_KEY', _settings.get('TELEGRAM_GATEWAY_KEY', '')).strip()
try:
    ALERT_COOLDOWN_SECONDS = max(15, int(os.environ.get(
        'ALERT_COOLDOWN_SECONDS', _settings.get('ALERT_COOLDOWN_SECONDS', '60'))))
except ValueError:
    raise ValueError('ALERT_COOLDOWN_SECONDS phải là số nguyên.') from None
