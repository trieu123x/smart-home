"""Download stage-1 and candidate weights listed in models.json into benchmark/weights/<id>/.

Checks sha256 when it is set; prints the hash when it is empty so it can be pinned.
`--pin` writes those hashes back into models.json.

Files with `"auth": "kaggle"` need a Kaggle API token in the KAGGLE_API_TOKEN environment variable.

Usage (from `Fall detection/`): .venv/Scripts/python -I benchmark/fetch_models.py [--only id1,id2] [--pin]
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BENCH = Path(__file__).resolve().parent
WEIGHTS = BENCH / 'weights'
MODELS_JSON = BENCH / 'models.json'
USER_AGENT = 'fallguard-benchmark/1.0'
MAX_BYTES = 2 << 30   # 2 GiB: no weight file or source video here comes close


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path, expected):
    """Refuse an unpinned or mismatching file. Called right before a pickle is loaded."""
    if not expected:
        raise ValueError(f'{path.name}: sha256 is not pinned in models.json (run fetch_models.py --pin)')
    digest = sha256_of(path)
    if digest != expected.lower():
        raise ValueError(f'{path.name}: sha256 {digest} does not match pinned {expected}')


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).scheme != 'https':
            raise urllib.error.URLError(f'refusing non-https redirect to {newurl}')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_HttpsOnlyRedirect)


def kaggle_token():
    """Kaggle API token from the environment only; it is never stored or printed."""
    token = os.environ.get('KAGGLE_API_TOKEN', '').strip()
    if not token:
        raise RuntimeError('set KAGGLE_API_TOKEN to download Kaggle model files')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', token):   # else http.client would echo it in an "Invalid header" error
        raise RuntimeError('KAGGLE_API_TOKEN has unexpected characters (pasted across lines?)')
    return token


def build_request(url, auth=None):
    """GET request for url. Credentials are unredirected headers, so urllib does not copy them
    to a redirect target (Kaggle redirects to signed Google Cloud Storage URLs)."""
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    if auth == 'kaggle':
        request.add_unredirected_header('Authorization', f'Bearer {kaggle_token()}')
    elif auth:
        raise ValueError(f'unknown auth: {auth!r}')
    return request


def download(url, dest, timeout=60, sha256=None, max_bytes=MAX_BYTES, auth=None):
    """Stream url into dest.part, hash it, and only rename to dest when the pin (if any) matches.

    Returns the sha256 of the downloaded file.
    """
    if urllib.parse.urlparse(url).scheme != 'https':
        raise ValueError(f'only https URLs are allowed: {url}')
    request = build_request(url, auth)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + '.part')
    digest, size = hashlib.sha256(), 0
    try:
        with _opener.open(request, timeout=timeout) as response, open(part, 'wb') as f:
            while chunk := response.read(1 << 20):
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError(f'download exceeds {max_bytes} bytes: {url}')
                digest.update(chunk)
                f.write(chunk)
        if sha256 and digest.hexdigest() != sha256.lower():
            raise ValueError(f'sha256 mismatch: got {digest.hexdigest()}, expected {sha256}')
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)
    return digest.hexdigest()


def safe_dest(model_id, rel):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', model_id):
        raise ValueError(f'invalid model id: {model_id!r}')
    dest = (WEIGHTS / model_id / rel).resolve()
    if not dest.is_relative_to((WEIGHTS / model_id).resolve()):
        raise ValueError(f'path escapes weights dir: {rel}')
    return dest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--only', default='', help='comma-separated model ids')
    parser.add_argument('--pin', action='store_true', help='write empty sha256 values back into models.json')
    args = parser.parse_args(argv)
    only = {m for m in args.only.split(',') if m}
    data = json.loads(MODELS_JSON.read_text(encoding='utf-8'))
    counts = {'ok': 0, 'downloaded': 0, 'failed': 0, 'missing': 0}
    pinned = False
    for entry in data['stage1'] + data['candidates']:
        if only and entry['id'] not in only:
            continue
        if entry.get('status') == 'missing':
            counts['missing'] += 1
            print(f"[MISSING] {entry['id']}: {entry.get('notes', '')}")
            continue
        for file in entry['files']:
            label = f"{entry['id']}/{file['path']}"
            try:
                dest = safe_dest(entry['id'], file['path'])
                fresh = not dest.is_file()
                if fresh:
                    print(f'[GET] {label} <- {file["url"]}', flush=True)
                    digest = download(file['url'], dest, sha256=file.get('sha256'), auth=file.get('auth'))
                else:
                    digest = sha256_of(dest)
                if not file.get('sha256'):
                    print(f'[PIN] {label} sha256={digest}')
                    if args.pin:
                        file['sha256'], pinned = digest, True
                elif digest != file['sha256'].lower():
                    dest.unlink()
                    raise ValueError(f'sha256 mismatch: got {digest}, expected {file["sha256"]}; file deleted')
                counts['downloaded' if fresh else 'ok'] += 1
            except Exception as e:
                counts['failed'] += 1
                print(f'[FAIL] {label}: {type(e).__name__}: {e}')
    if pinned:
        MODELS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        print('[PIN] models.json updated')
    print('Summary: ' + ', '.join(f'{k}={v}' for k, v in counts.items()))
    return 1 if counts['failed'] else 0


if __name__ == '__main__':
    sys.exit(main())
