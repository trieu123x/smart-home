"""Safe diagnostics for FallGuard -> Telegram Gateway connection.

Never prints API keys. Read-only unless called with --send-test.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from fallguard import telegram_config as settings


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # Never forward a gateway secret to a redirected host.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url, *, data=None, key=None):
    headers = {"Accept": "application/json"}
    if key is not None:
        headers["X-Gateway-Key"] = key
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, headers=headers, data=data,
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=12) as response:
            return response.status, response.headers, response.read(32_000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read(32_000)
    except (OSError, ValueError) as exc:
        return None, {}, type(exc).__name__.encode()


def read_env_occurrences():
    path = ROOT / ".env"
    if not path.is_file():
        print("[FAIL] Project root .env not found:", path)
        return {}
    found = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        name = name.strip()
        if name in ("TELEGRAM_GATEWAY_URL", "TELEGRAM_GATEWAY_KEY"):
            found.setdefault(name, []).append(value.strip().strip('"\''))
    return found


def check():
    print("[1] Local FallGuard config")
    entries = read_env_occurrences()
    for name in ("TELEGRAM_GATEWAY_URL", "TELEGRAM_GATEWAY_KEY"):
        values = entries.get(name, [])
        if not values:
            print("  [FAIL] Missing in .env:", name)
        if len(values) > 1:
            print("  [WARN] Duplicate lines in .env:", name)
        if name in os.environ:
            in_file = bool(values) and os.environ[name].strip() != values[-1]
            print("  [WARN] Windows environment overrides .env:", name,
                  "(different from .env)" if in_file else "(same value)")
        else:
            print("  [OK] From .env:", name)
    key = settings.GATEWAY_API_KEY
    base = settings.GATEWAY_URL.rstrip("/")
    url = urlsplit(base)
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        print("  [FAIL] Gateway URL must be https://YOUR-DOMAIN")
        return False
    if len(key) < 24 or any(c.isspace() for c in key):
        print("  [FAIL] Gateway key missing / shorter than 24 / contains whitespace")
        return False
    print("  [OK] Host:", url.hostname)
    print("  [OK] Key loaded, length:", len(key), "(value hidden)")

    print("[2] Remote health check (does NOT send notifications)")
    status, headers, body = request(base + "/healthz")
    print("  Status:", status or "network error")
    if status == 200:
        print("  [OK] Vercel app is reachable")
    elif status in (401, 403):
        print("  [WARN] /healthz is blocked. Check Vercel Deployment Protection / domain.")
    else:
        print("  [WARN] Verify production domain and deployment")

    print("[3] Gateway route check (does NOT send notifications)")
    status, headers, body = request(base + "/openapi.json")
    print("  Status:", status or "network error")
    if status == 200:
        try:
            routes = json.loads(body).get("paths", {})
            if "/gateway/v1/notify" in routes:
                print("  [OK] /gateway/v1/notify exists in this deployment")
            else:
                print("  [FAIL] Gateway route is missing: deploy updated Telegram-bot")
        except (ValueError, AttributeError):
            print("  [WARN] /openapi.json is not valid FastAPI OpenAPI JSON")
    else:
        print("  [WARN] Cannot verify route; inspect domain/deployment protection")

    return True


def send_test():
    print("[4] Sending one test notification to ALL subscribed Telegram users")
    base = settings.GATEWAY_URL.rstrip("/")
    payload = json.dumps({"title": "FallGuard Gateway test", "message":
                          "Kiểm tra kết nối từ FallGuard tới Telegram Gateway.",
                          "level": "info"}, ensure_ascii=False).encode("utf-8")
    code, headers, data = request(base + "/gateway/v1/notify", data=payload,
                                  key=settings.GATEWAY_API_KEY)
    print("  HTTP status:", code or "network error")
    media_type = (headers.get("Content-Type", "") if headers else "").lower()
    if "json" in media_type:
        try:
            obj = json.loads(data)
        except ValueError:
            obj = {}
        if isinstance(obj, dict):
            detail = obj.get("detail")
            if detail in ("Invalid gateway key", "Gateway credentials not configured",
                          "Subscriber database unavailable",
                          "Too many subscribers for synchronous dispatch; configure a job queue"):
                print("  Server detail:", detail)
            if code == 200:
                print("  Sent:", obj.get("sent"), "Subscribers:", obj.get("subscribers"),
                      "Failed:", obj.get("failed"), "Blocked:", obj.get("blocked"))
    if code == 401:
        print("  [FAIL] Gateway authentication mismatch. Check Vercel GATEWAY_API_KEYS Value and Production deployment.")
    elif code == 403:
        print("  [FAIL] Forbidden. If response is HTML, inspect Vercel Deployment Protection (not the Gateway key).")
    elif code == 503:
        print("  [FAIL] Gateway not configured or Supabase unavailable; check Vercel Runtime Logs.")
    elif code == 200:
        print("  [OK] Gateway request accepted (delivery counts above)")
    elif code is None:
        print("  [FAIL] Network error or timeout")
    else:
        print("  [WARN] Unexpected status. Inspect Vercel Runtime Logs.")
    print("  Response type:", media_type.split(';')[0] if media_type else "unknown")


if __name__ == "__main__":
    if check() and "--send-test" in sys.argv:
        send_test()
    elif "--send-test" not in sys.argv:
        print("To send one test notification, run: CHECK_GATEWAY.bat test")
