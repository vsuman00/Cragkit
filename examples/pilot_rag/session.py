"""Explicit development-only provisioning; the child uses an installed wheel."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from check_postgres import migrations, migration_script
from qdrant_source_native import PostgresSourceFixture
from qdrant_publication_native import PublicationDatabase


async def provision(fixture):
    from psycopg import sql
    admin = await PublicationDatabase._connect(fixture.config)
    configs = {}
    tables = ('collections', 'documents', 'document_revisions', 'index_generations',
              'chunks', 'chunk_lexical', 'document_grants', 'ingestion_jobs', 'migration_history')
    try:
        await admin.execute(migration_script(migrations(ROOT / 'storage/postgres/migrations'), apply=True), prepare=False)
        await admin.execute((ROOT / 'storage/postgres/deployment/neon.sql').read_text(), prepare=False)
        async with admin.transaction():
            for profile in ('reader', 'writer'):
                role = 'manual_pilot_' + profile
                password = secrets.token_hex(32)
                await admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS '
                    'NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT CONNECTION LIMIT 1').format(
                        sql.Identifier(role), sql.Literal(password)))
                await admin.execute(sql.SQL('GRANT USAGE ON SCHEMA cragkit TO {}').format(sql.Identifier(role)))
                await admin.execute(sql.SQL('GRANT USAGE ON DOMAIN cragkit.identity_text,cragkit.collection_text,'
                    'cragkit.sha256_hex,cragkit.safe_count TO {}').format(sql.Identifier(role)))
                for table in tables:
                    history = table == 'migration_history'
                    permissions = 'SELECT' if history or profile == 'reader' else 'SELECT,INSERT,UPDATE'
                    await admin.execute(sql.SQL('GRANT ' + permissions + ' ON cragkit.{} TO {}').format(
                        sql.Identifier(table), sql.Identifier(role)))
                    predicate = sql.SQL('true') if history else sql.SQL(
                        "tenant_id=current_setting('cragkit.tenant_id',true) AND tenant_id IN ('team','other') "
                        "AND collection_id='manual-pilot'")
                    await admin.execute(sql.SQL('CREATE POLICY manual_pilot_scope_{} ON cragkit.{} '
                        'FOR ALL TO {} USING ({}) WITH CHECK ({})').format(
                            sql.SQL(profile), sql.Identifier(table), sql.Identifier(role), predicate, predicate))
                configs[profile] = fixture.reader_config(role, password)
        return configs
    finally:
        await asyncio.wait_for(admin.close(), 3)


async def session(args):
    # Keep the venv path: resolving its symlink would invoke the base interpreter.
    interpreter = args.python.absolute()
    if not interpreter.is_file():
        raise ValueError('installed_interpreter_missing')
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith('PG') and key not in ('PYTHONPATH', 'PYTHONHOME')}
    output = ROOT / 'artifacts/V5/manual-pilot'
    output.mkdir(parents=True, exist_ok=True)
    with PostgresSourceFixture(args.postgres_bin, output) as fixture:
        config = await provision(fixture)
        port = config['reader']['port']
        with tempfile.TemporaryDirectory(prefix='manual-pilot-', dir=output) as private:
            os.chmod(private, 0o700)
            config_path = Path(private) / 'runtime.json'
            descriptor = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w') as destination:
                json.dump(config, destination)
            command = [str(interpreter), '-I', str(HERE / 'app.py'), '--config', str(config_path),
                       '--corpus', str(args.corpus.absolute())]
            if args.smoke:
                command.append('--smoke')
            child = await asyncio.create_subprocess_exec(*command, cwd=HERE, env=environment)
            try:
                code = await asyncio.wait_for(child.wait(), 180 if args.smoke else 3600)
            finally:
                if child.returncode is None:
                    child.terminate()
                    try:
                        await asyncio.wait_for(child.wait(), 5)
                    except TimeoutError:
                        child.kill()
                        await asyncio.wait_for(child.wait(), 5)
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex(('127.0.0.1', port)) == 0:
            raise RuntimeError('owned_listener_remains')
    if code != 0:
        raise RuntimeError('application_failed')
    print('cleanup_verified=true; disposable database and private credentials removed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', type=Path, default=HERE / '.venv/bin/python')
    parser.add_argument('--postgres-bin', type=Path, default=Path('/opt/homebrew/opt/postgresql@17/bin'))
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--corpus', type=Path, default=HERE / 'corpus.json')
    args = parser.parse_args()
    if args.smoke and args.corpus.absolute() != HERE / 'corpus.json':
        parser.error('--smoke requires the bundled synthetic corpus')
    try:
        asyncio.run(session(args))
    except KeyboardInterrupt:
        print('Session interrupted; owned cleanup completed.')
    except Exception:
        print('session_failed: check installed wheel, PostgreSQL 17.11 and corpus; '
              'private diagnostics withheld', file=sys.stderr)
        raise SystemExit(1) from None
