"""Explicit disposable QP-r1 SQL schema/permission checks, without Qdrant."""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
import traceback

from qdrant_authority_schema import catalog_queries
from qdrant_purge_native import seed_documents, install, guard_probes
from qdrant_purge_schema import CHECKS, run_sql_probes, run_historical_confirmation
from qdrant_security_guard_native import SecurityGuardDatabase, rows
from qdrant_source_native import PostgresSourceFixture
from runtime_diagnostics import describe_error

PROOF_SCOPE = 'security_owners_and_managed_erasure_sql_only'


async def check(fixture, progress, *, seed_only=False):
    progress['stage'] = 'operator_bootstrap'
    async with SecurityGuardDatabase(fixture, with_attestations=True) as database:
        progress['stage'] = 'native_writer_seed'
        purge, guards = await seed_documents(database)
        if seed_only:
            return dict(checks=['native_writer_committed_purge_and_security_owner_fixtures'],
                        proof_scope='synthetic_native_sql_fixture_only')
        progress['stage'] = 'profile5_install_and_rollback'
        source = await install(database)
        progress['stage'] = 'capability_inventory'
        capability_query = (Path(__file__).resolve().parents[1]/'contracts/sql/qdrant_purge_capabilities.sql').read_text()
        capability_fingerprint = (await rows(database.admin, capability_query))[0][0]
        progress['stage'] = 'security_owner_guard_branches'
        checks = await guard_probes(database, guards)
        progress['stage'] = 'restricted_purge_sql_probes'
        observed = await run_sql_probes(database, purge)
        if observed != list(CHECKS):
            raise RuntimeError('purge_sql_probe_result_shape')
        checks += observed
        progress['stage'] = 'committed_erasure_read_only_confirmation'
        checks += await run_historical_confirmation(database, purge)
        history = await rows(database.admin,
            'SELECT version,checksum_sha256 FROM cragkit_qdrant.schema_migrations ORDER BY version LIMIT 6')
        if len(history) != 5 or tuple(history[-1]) != (source.version, source.checksum):
            raise RuntimeError('purge_history_profile')
        query = catalog_queries()[0]
        return dict(checks=checks, proof_scope=PROOF_SCOPE,
            migration=dict(version=source.version, checksum_sha256=source.checksum),
            history=[list(row) for row in history], query_sha256=sha256(query.encode()).hexdigest(),
            catalog_fingerprint=(await rows(database.admin, query))[0][0],
            capability_fingerprint=capability_fingerprint,
            capability_query_sha256=sha256(capability_query.encode()).hexdigest(),
            catalog=json.loads((await rows(database.admin, catalog_queries()[1]))[0][0]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin', type=Path, required=True)
    parser.add_argument('--artifacts-dir', type=Path, required=True)
    parser.add_argument('--allow-local-processes', action='store_true', required=True)
    parser.add_argument('--preflight-seed', action='store_true')
    args = parser.parse_args(argv)
    progress = dict(stage='admission')
    artifacts_owned = False
    try:
        if args.artifacts_dir.exists():
            raise RuntimeError('purge_sql_fresh_artifacts_required')
        args.artifacts_dir.mkdir(mode=0o700, parents=True)
        artifacts_owned = True
        private = Path(tempfile.mkdtemp(prefix='postgres-', dir=args.artifacts_dir)).resolve()
        with PostgresSourceFixture(args.postgres_bin, private/'server', max_connections=6) as fixture:
            result = asyncio.run(asyncio.wait_for(check(fixture, progress, seed_only=args.preflight_seed), 180))
        shutil.rmtree(private)
        result = dict(ok=True, **result, cleanup_verified=True)
        (args.artifacts_dir/'results.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(dict(ok=True, checks=len(result['checks']), proof_scope=result['proof_scope'], cleanup_verified=True)))
        return 0
    except Exception as error:
        if artifacts_owned:
            root = Path(__file__).resolve().parents[1]
            locations = []
            for frame in traceback.extract_tb(error.__traceback__):
                try:
                    relative = Path(frame.filename).resolve().relative_to(root)
                except ValueError:
                    continue
                if relative.parts[0] in ('tools', 'packages'):
                    locations.append(dict(path=str(relative), line=frame.lineno))
            (args.artifacts_dir/'failure-locations.json').write_text(json.dumps(locations)+'\n')
            # This fixture owns only synthetic data. Permission diagnostics name
            # fixed SQL objects and help isolate grants without logging statements.
            if getattr(error, 'sqlstate', None) == '42501':
                (args.artifacts_dir/'permission-failure.json').write_text(json.dumps(dict(
                    message=error.diag.message_primary, context=error.diag.context))+'\n')
        print(json.dumps(dict(ok=False, stage=progress['stage'],
            error=describe_error(error, operation='primary', stage='fixture_setup'))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
