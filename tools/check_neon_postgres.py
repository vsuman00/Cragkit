"""Explicit Neon administrative migration, hardening and isolated security checks."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import re

from check_postgres import (migrations, migration_script, VECTOR_SETUP_DIRECTORY,
                            VectorCompatibilityError, vector_compatibility_error,
                            vector_inspection_script, parse_vector_inspection, vector_setup_script)
from check_python_postgres import load_config, require_client_tls, require_neon_host

ROOT = Path(__file__).resolve().parents[1]
CURRENT_STAGE = 'authorization'


class NeonCheckError(RuntimeError):
    pass


async def execute_script(connection, script: str, marker: str) -> list[str]:
    """Drain every result and require the exact one-column success observation."""
    require_client_tls(connection)
    try:
        cursor = await connection.execute(script, prepare=False)
        observed = False
        lines = []
        while True:
            if cursor.description is not None:
                for row in await cursor.fetchall():
                    if len(row) == 1 and isinstance(row[0], str):
                        lines.append(row[0])
                    if tuple(row) == (marker,):
                        observed = True
            if not cursor.nextset():
                break
        if not observed:
            raise NeonCheckError('missing_success_marker')
        return lines
    except Exception as error:
        compatibility = vector_compatibility_error(getattr(error, 'sqlstate', None))
        if compatibility is not None:
            raise compatibility from None
        raise


async def check(config_path: Path, *, apply: bool, harden: bool = False,
                integration: bool = False, security: bool = False,
                vector: bool = False, install_vector: bool = False,
                allow_managed_primitives: bool = False) -> None:
    global CURRENT_STAGE
    if allow_managed_primitives and not (vector or install_vector):
        raise NeonCheckError('managed_primitives_require_vector')
    if install_vector and not apply:
        raise NeonCheckError('vector_install_requires_apply')
    CURRENT_STAGE = 'configuration'
    # Native dependencies are loaded only after explicit CLI authorization.
    import psycopg
    from cragkit._postgres_pool import PoolResource, parse_pool_config

    config = parse_pool_config(load_config(config_path))
    require_neon_host(config.host)
    PoolResource(config)._check_owned_configuration()
    scripts = [('migrations', migration_script(migrations(ROOT / 'storage/postgres/migrations'), apply=apply), 'cragkit_migration_ok')]
    if vector or install_vector:
        scripts.insert(0, ('vector-inspection', vector_inspection_script(), 'cragkit_vector_inspection_ok'))
        scripts.append(('vector-setup', vector_setup_script(migrations(VECTOR_SETUP_DIRECTORY)[0], apply=install_vector, allow_managed_primitives=allow_managed_primitives), 'cragkit_vector_ok'))
    if harden:
        scripts.append(('hardening', (ROOT / 'storage/postgres/deployment/neon.sql').read_text(), 'cragkit_neon_hardening_ok'))
    if integration:
        scripts.append(('integration', (ROOT / 'storage/postgres/tests/invariants.sql').read_text(), 'cragkit_migration_ok'))
    if security:
        scripts.append(('security', (ROOT / 'storage/postgres/tests/security.sql').read_text(), 'cragkit_security_probe_ok'))
    connection = None
    try:
        CURRENT_STAGE = 'connection'
        connection = await psycopg.AsyncConnection.connect(
            host=config.host, port=config.port, dbname=config.dbname, user=config.user,
            sslmode='verify-full', sslrootcert=str(config.sslrootcert), passfile=str(config.passfile),
            connect_timeout=5, autocommit=True, application_name='cragkit-neon-admin-check',
            options='-c statement_timeout=30000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=30000')
        require_client_tls(connection)
        for stage, script, marker in scripts:
            CURRENT_STAGE = stage
            lines = await execute_script(connection, script, marker)
            if stage == 'vector-inspection':
                observation = parse_vector_inspection(lines, database=config.dbname, user=config.user)
                print(json.dumps(observation, sort_keys=True))
    finally:
        if connection is not None:
            await asyncio.wait_for(connection.close(), 3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--confirm-dedicated-target', action='store_true', required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--apply', action='store_true')
    action.add_argument('--check', action='store_true')
    parser.add_argument('--harden', action='store_true')
    parser.add_argument('--integration', action='store_true')
    parser.add_argument('--security', action='store_true')
    parser.add_argument('--allow-test-writes', action='store_true')
    parser.add_argument('--vector', action='store_true')
    parser.add_argument('--install-vector', action='store_true')
    parser.add_argument('--allow-managed-vector-primitives', action='store_true')
    args = parser.parse_args()
    if args.allow_managed_vector_primitives and not (args.vector or args.install_vector):
        print('Managed vector primitives require --vector or --install-vector.')
        return 2
    if args.install_vector and not args.apply:
        print('Neon vector installation requires --apply.')
        return 2
    if (args.integration or args.security) and not args.allow_test_writes:
        print('Neon administrative checks require explicit test-write authorization.')
        return 2
    try:
        async def bounded():
            async with asyncio.timeout(120):
                await check(args.config, apply=args.apply, harden=args.harden,
                            integration=args.integration, security=args.security,
                            vector=args.vector or args.install_vector, install_vector=args.install_vector,
                            allow_managed_primitives=args.allow_managed_vector_primitives)
        asyncio.run(bounded())
    except Exception as error:
        kind = type(error).__name__
        kind = kind if re.fullmatch(r'[A-Za-z_]{1,80}', kind) else 'Exception'
        state = getattr(error, 'sqlstate', None)
        state = state if isinstance(state, str) and re.fullmatch(r'[A-Z0-9]{5}', state) else 'none'
        print(f'Neon administrative checks failed: {kind}; SQLSTATE={state}; stage={CURRENT_STAGE}.')
        return 1
    print('Neon administrative checks passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
