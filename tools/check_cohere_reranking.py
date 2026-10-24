"""Opt-in, single-request Cohere probe using the public synthetic fixture."""
from __future__ import annotations

import argparse
import asyncio
import http.client
import json
import math
import os
from pathlib import Path
import ssl
import stat
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODEL = "rerank-v5.0-fast"
PROFILE = {
    "profile_id": "cohere_v5fast_probe_v1", "provider": "cohere", "model": MODEL,
    "model_revision": "mutable_alias:" + MODEL, "score_kind": "relevance_score",
    "score_direction": "higher_is_better", "preprocessing_revision": "ascii_short_probe_v1",
    "truncation_policy": "reject",
}
RESPONSE_CAP = 65536
# Conservative admission for the complete two-runtime probe, not actual billing.
PAIR_REQUESTS = 2
MAX_DOCUMENTS = 3
ADMISSION_TOKENS_PER_DOCUMENT = 32768
PRICE_USD_PER_MILLION_TOKENS = 0.02


class ProbeFailure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def read_key() -> str:
    """Read only the fixed owner-private file; never emit its path or contents."""
    directory = Path.home() / ".config/cragkit/cohere"
    for parent in (directory.parent.parent, directory.parent, directory):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ProbeFailure("credential_permissions")
    info = directory.lstat()
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise ProbeFailure("credential_permissions")
    # Resolve the directory once to prevent a later parent-path substitution.
    dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        opened_dir = os.fstat(dir_fd)
        if (opened_dir.st_dev, opened_dir.st_ino) != (info.st_dev, info.st_ino):
            raise ProbeFailure("credential_permissions")
        fd = os.open("api-key", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 4096):
                raise ProbeFailure("credential_permissions")
            raw = os.read(fd, 4097)
        finally:
            os.close(fd)
    finally:
        os.close(dir_fd)
    if len(raw) > 4096:
        raise ProbeFailure("credential_invalid")
    key = raw.decode("ascii").strip()
    if not key or any(ord(char) < 33 or ord(char) > 126 for char in key):
        raise ProbeFailure("credential_invalid")
    if key.startswith(("sk-proj-", "sk-svcacct-")):
        raise ProbeFailure("credential_provider_mismatch")
    return key


def sample() -> dict[str, Any]:
    fixture = json.loads((ROOT / "contracts/fixtures/reranking.json").read_text())
    value = fixture["sample"]
    candidates = value["candidates"]
    if not 1 <= len(candidates) <= 3:
        raise ProbeFailure("fixture_bounds")
    for text in [value["query"], *[row["text"] for row in candidates]]:
        if type(text) is not str or not text or len(text.encode("ascii")) > 256:
            raise ProbeFailure("fixture_bounds")
    return value


def request(body: bytes, key: str, timeout: float, observation: dict[str, Any]) -> bytes:
    # HTTPSConnection uses neither proxy environment variables nor redirect handling.
    connection = http.client.HTTPSConnection("api.cohere.com", timeout=timeout,
                                              context=ssl.create_default_context())
    try:
        observation["provider_calls"] = 1
        connection.request("POST", "/v2/rerank", body=body, headers={
            "Authorization": "Bearer " + key, "Content-Type": "application/json",
            "Accept": "application/json",
        })
        response = connection.getresponse()
        observation["http_status"] = response.status
        if response.status != 200:
            raise ProbeFailure("provider_http_status")
        raw = response.read(RESPONSE_CAP + 1)
        if len(raw) > RESPONSE_CAP:
            raise ProbeFailure("provider_response_limit")
        return raw
    finally:
        connection.close()


async def check() -> dict[str, Any]:
    from cragkit.reranking import RerankProfile, RerankingAdapter

    observation: dict[str, Any] = {"http_status": None, "billed_input_tokens": None,
        "provider_calls": 0, "request_id_present": False}
    started = time.monotonic()
    try:
        admission_usd = (PAIR_REQUESTS * MAX_DOCUMENTS * ADMISSION_TOKENS_PER_DOCUMENT
                         * PRICE_USD_PER_MILLION_TOKENS / 1_000_000)
        if admission_usd >= 0.01:
            raise ProbeFailure("admission_cost_limit")
        value = sample()
        key = read_key()

        async def transport(body: bytes, *, deadline: float, max_response_bytes: int) -> bytes:
            boundary = json.loads(body)
            candidates = boundary["candidates"]
            payload = json.dumps({"model": MODEL, "query": boundary["query"],
                "documents": [row["text"] for row in candidates], "top_n": len(candidates),
                "max_tokens_per_doc": 1024}, separators=(",", ":")).encode("ascii")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProbeFailure("deadline_exceeded")
            raw = await asyncio.to_thread(request, payload, key, min(20.0, remaining), observation)
            parsed = json.loads(raw)
            observation["request_id_present"] = type(parsed.get("id")) is str and bool(parsed["id"])
            rows = parsed["results"]
            if type(rows) is not list or len(rows) != len(candidates):
                raise ProbeFailure("provider_mapping_invalid")
            normalized = []
            for row in rows:
                index = row["index"]
                score = row["relevance_score"]
                if (type(index) is not int or not 0 <= index < len(candidates)
                        or type(score) not in (int, float) or not math.isfinite(score)):
                    raise ProbeFailure("provider_mapping_invalid")
                normalized.append({"candidate_id": candidates[index]["candidate_id"], "raw_score": score})
            tokens = parsed.get("meta", {}).get("billed_units", {}).get("input_tokens")
            if type(tokens) is int and tokens >= 0:
                observation["billed_input_tokens"] = tokens
            encoded = json.dumps(normalized, allow_nan=False).encode("ascii")
            if len(encoded) > max_response_bytes:
                raise ProbeFailure("provider_response_limit")
            return encoded

        ranked = await RerankingAdapter(transport, profile=RerankProfile(**PROFILE), allow_live=True).rank(
            value["query"], value["candidates"], deadline=time.monotonic() + 25,
            max_provider_calls=1, allow_fallback=False)
        return {"state": "passed", "runtime": "python", **ranked, **observation,
            "observed_ms": round((time.monotonic() - started) * 1000, 3),
            "api_version": "2", "processed_tokens": None, "provider_truncation": "unknown",
            "weight_revision": "mutable_alias", "admission_pair_upper_usd": admission_usd}
    except Exception as error:
        # Exception messages, provider bodies, headers and credential paths are private.
        code = error.code if isinstance(error, ProbeFailure) else "probe_failed"
        return {"state": "failed", "runtime": "python", "error_code": code,
            "http_status": observation["http_status"],
            "provider_calls": observation["provider_calls"],
            "observed_ms": round((time.monotonic() - started) * 1000, 3)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-live", action="store_true", required=True)
    parser.parse_args()
    try:
        result = asyncio.run(check())
    except Exception:
        result = {"state": "failed", "runtime": "python", "error_code": "probe_failed"}
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["state"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
