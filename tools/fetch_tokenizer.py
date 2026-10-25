"""Explicitly acquire the pinned tokenizer table; library imports never fetch it."""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'artifacts/tokenizers/cl100k_base.tiktoken'
URL = 'https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken'
SHA256 = '223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7'
MAX_BYTES = 2_000_000


def acquire():
    if TARGET.exists():
        with TARGET.open('rb') as stream:
            raw = stream.read(MAX_BYTES+1)
        if len(raw) <= MAX_BYTES and hashlib.sha256(raw).hexdigest() == SHA256:
            return {'state':'passed','source':'verified_cache','bytes':len(raw),'sha256':SHA256}
        raise ValueError('tokenizer_cache_integrity')
    with urllib.request.urlopen(URL, timeout=30) as response:
        raw = response.read(MAX_BYTES+1)
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError('tokenizer_download_integrity')
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with TARGET.open('xb') as stream:
        stream.write(raw)
    return {'state':'passed','source':'pinned_download','bytes':len(raw),'sha256':SHA256}


def main():
    try:
        result = acquire()
    except Exception:
        print(json.dumps({'state':'failed','code':'tokenizer_asset_unavailable'}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
