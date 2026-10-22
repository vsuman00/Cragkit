"""Run an authorized lexical query from an installed cragkit[postgres] wheel.

Usage: python postgres.py /absolute/private/runtime.json /absolute/request.json
The application supplies trusted scope separately from the retrieval request.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import stat
import sys

from cragkit.contracts import parse_request, parse_scope
from cragkit.postgres import PoolResource, PostgresRetriever, parse_pool_config


async def main(config_path: Path, input_path: Path) -> None:
    info = config_path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Private configuration required")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    for key in ("sslrootcert", "passfile"):
        config[key] = Path(config[key])
    supplied = json.loads(input_path.read_text(encoding="utf-8"))
    request = parse_request(supplied["request"])
    scope = parse_scope(supplied["scope"])
    resource = PoolResource(parse_pool_config(config))
    try:
        await resource.open()
        result = await PostgresRetriever(resource).retrieve(
            request, scope=scope, deadline=asyncio.get_running_loop().time() + 20)
        print(result.model_dump_json())
    finally:
        await resource.close()


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3:
            raise ValueError("Expected configuration and input paths")
        asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2])))
    except Exception:
        print('{"state":"failed","code":"example_failed"}', file=sys.stderr)
        raise SystemExit(1) from None
