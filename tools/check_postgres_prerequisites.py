"""Explicitly verify the private native V6 database prerequisite, without inference."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import socket

from postgres_vector_fixture import V6PostgresFixture


async def verify(postgres_bin: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError('v6_prerequisite_output_exists')
    output.mkdir(parents=True, mode=0o700)
    fixture = V6PostgresFixture(postgres_bin, output)
    result = {'state': 'running', 'live_inference': False, 'cleanup_verified': False}
    try:
        with fixture:
            await fixture.provision(tenants=('v6-tenant',), collections=('v6-prerequisite',))
            host, port = fixture.config['host'], fixture.config['port']
            result['checks'] = list(fixture.checks)
        try:
            connection = socket.create_connection((host, port), timeout=.2)
        except ConnectionRefusedError:
            pass
        else:
            connection.close()
            raise RuntimeError('v6_postgres_listener_remains')
        result.update(state='passed', cleanup_verified=True)
    except BaseException as error:
        result.update(state='failed', error=type(error).__name__)
        raise
    finally:
        (output / 'results.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared-postgres-bin', type=Path, required=True)
    parser.add_argument('--artifacts-dir', type=Path, required=True)
    parser.add_argument('--allow-local-processes', action='store_true', required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(verify(args.prepared_postgres_bin, args.artifacts_dir))
    except Exception:
        print(json.dumps({'state': 'failed', 'code': 'v6_native_prerequisite_failed'}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
