"""HTTP client for the EXISTING Telegram-bot FastAPI notification gateway.

FallGuard NEVER stores or uses Telegram bot tokens, chat IDs or Supabase credentials.
The gateway endpoint comes from environment settings; requests use X-Gateway-Key.
"""
import base64
import json
import urllib.error
import urllib.parse
import urllib.request

from .telegram_config import GATEWAY_API_KEY, GATEWAY_PATH, GATEWAY_URL


class TelegramError(RuntimeError):
    """Safe diagnostic text (never contains gateway secrets)."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward an API key to a redirected host."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _gateway_endpoint():
    url = GATEWAY_URL.rstrip('/')
    try:
        parts = urllib.parse.urlsplit(url)
        valid = (parts.scheme == 'https' and bool(parts.hostname)
                 and not parts.username and not parts.password
                 and not parts.query and not parts.fragment
                 and parts.path in ('', '/'))
    except ValueError:
        valid = False
    if not valid:
        raise TelegramError('TELEGRAM_GATEWAY_URL phải là địa chỉ HTTPS gốc của bot Vercel.')
    path = GATEWAY_PATH
    if (not path.startswith('/') or path.startswith('//')
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in path)
            or any(c in path for c in ('\\', '?', '#'))):
        raise TelegramError('TELEGRAM_GATEWAY_PATH phải là đường dẫn bắt đầu bằng một dấu /, '
                            'không kèm domain, query hoặc fragment. Kiểm tra .env.')
    return url + path


def is_configured():
    try:
        _gateway_endpoint()
    except TelegramError:
        return False
    return len(GATEWAY_API_KEY) >= 24 and not any(c.isspace() for c in GATEWAY_API_KEY)


def send_notification(*, title, message, level='info', event_id=None, image_jpeg=None):
    """Submit one notification; the gateway broadcasts to all /start subscribers.

    Returns parsed gateway stats; raises TelegramError for authorization, transport,
    no subscribers, or partial delivery. A JPEG snapshot may be attached.
    """
    endpoint = _gateway_endpoint()
    if not is_configured():
        raise TelegramError('Thiếu TELEGRAM_GATEWAY_KEY (cần API key đủ mạnh).')
    if level not in ('info', 'warning', 'critical'):
        raise TelegramError('Cấp độ thông báo không hợp lệ.')
    if not isinstance(title, str) or not 0 < len(title.strip()) <= 120:
        raise TelegramError('Tiêu đề cảnh báo không hợp lệ.')
    if not isinstance(message, str) or not 0 < len(message.strip()) <= 3500:
        raise TelegramError('Nội dung cảnh báo trống hoặc quá dài.')
    payload = {'title': title.strip(), 'message': message.strip(), 'level': level}
    if event_id is not None:
        payload['event_id'] = event_id
    if image_jpeg is not None:
        if (not isinstance(image_jpeg, bytes) or len(image_jpeg) > 2_000_000
                or not image_jpeg.startswith(b'\xff\xd8\xff')
                or not image_jpeg.endswith(b'\xff\xd9')):
            raise TelegramError('Ảnh cảnh báo phải là JPEG hợp lệ, tối đa 2 MB.')
        payload['image_base64'] = base64.b64encode(image_jpeg).decode('ascii')
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(endpoint, data=data, headers={
        'X-Gateway-Key': GATEWAY_API_KEY,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }, method='POST')
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=60) as response:
            response_data = response.read(16_384)
        result = json.loads(response_data)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise TelegramError('Gateway báo HTTP 401: API key không khớp. Kiểm tra GATEWAY_API_KEYS trong Production của Vercel; thử chạy CHECK_GATEWAY.bat.') from None
        if exc.code == 403:
            raise TelegramError('Gateway báo HTTP 403: bị chặn quyền truy cập. Kiểm tra Vercel Deployment Protection và Runtime Logs; không nhất thiết do sai API key.') from None
        if exc.code == 404:
            raise TelegramError('Gateway báo HTTP 404: không tìm thấy endpoint. '
                                'Kiểm tra TELEGRAM_GATEWAY_URL và TELEGRAM_GATEWAY_PATH '
                                'có khớp route đã deploy của bot không.') from None
        if exc.code == 422:
            raise TelegramError('Gateway từ chối định dạng cảnh báo (HTTP 422). Nếu gửi kèm ảnh, hãy cập nhật Telegram-bot Gateway trên Vercel trước.') from None
        if exc.code in (429, 503, 504):
            raise TelegramError(f'Gateway đang bận/không khả dụng (HTTP {exc.code}).') from None
        raise TelegramError(f'Gateway báo HTTP {exc.code}.') from None
    except (OSError, ValueError, UnicodeError):
        # Do not include exception repr: it might contain authorization headers.
        raise TelegramError('Không thể kết nối Gateway hoặc phản hồi không hợp lệ.') from None

    if not isinstance(result, dict) or result.get('ok') is not True:
        raise TelegramError('Gateway gửi thông báo không thành công hoặc chỉ gửi được một phần.')
    if result.get('duplicate'):
        # The same event_id was claimed on Vercel already; do not claim a fresh send.
        return {'sent': False, 'reason': 'duplicate', 'gateway': result}
    sent = result.get('sent', 0)
    if not isinstance(sent, int) or isinstance(sent, bool) or sent < 1:
        raise TelegramError('Gateway chưa gửi đến ai. Hãy kiểm tra người dùng đã /start trong bot Telegram.')
    if image_jpeg is not None and result.get('photo') is not True:
        raise TelegramError('Gateway chưa xác nhận gửi ảnh. Hãy cập nhật Gateway trên Vercel trước khi thử lại.')
    return {'sent': True, 'recipients': sent, 'photo': result.get('photo') is True, 'gateway': result}
