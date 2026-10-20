"""Password-protected control panel and publisher. Fail closed without a password."""
import hmac
import os
import secrets
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from .telegram_config import _settings

ADMIN_PASSWORD = os.environ.get('FALLGUARD_PASSWORD', _settings.get('FALLGUARD_PASSWORD', ''))
COOKIE_NAME = 'fallguard_session'
SESSION_AGE = 7 * 24 * 3600


class Auth:
    def __init__(self, password=ADMIN_PASSWORD):
        self.password = password
        self.sessions = {}
        self.failed = defaultdict(deque)

    @property
    def configured(self):
        return len(self.password) >= 12

    def login(self, password, ip):
        now = time.monotonic()
        attempts = self.failed[ip]
        while attempts and now - attempts[0] > 300:
            attempts.popleft()
        if len(attempts) >= 10:
            return None, 'too_many_attempts'
        if not self.configured or not hmac.compare_digest(password.encode(), self.password.encode()):
            attempts.append(now)
            return None, 'invalid_credentials'
        attempts.clear()
        session = secrets.token_urlsafe(32)
        self.sessions[session] = time.time() + SESSION_AGE
        return session, None

    def valid(self, token):
        if not token:
            return False
        expiry = self.sessions.get(token)
        return expiry is not None and expiry > time.time()

    def logout(self, token):
        self.sessions.pop(token, None)


def same_origin(headers):
    """Reject cross-site browser commands and websocket connections."""
    origin = headers.get('origin')
    if origin:
        try:
            url = urlsplit(origin)
            if url.scheme not in ('http', 'https') or url.netloc.lower() != headers.get('host', '').lower():
                return False
        except ValueError:
            return False
    return headers.get('sec-fetch-site', '').lower() not in ('cross-site',)
