"""Explicit disposable SG-r2 operator, permission and atomic-lock SQL acceptance."""
from __future__ import annotations

import argparse
import asyncio
import json
from hashlib import sha256
from pathlib import Path
import shutil
import tempfile

from qdrant_authority_schema import catalog_queries
from qdrant_source_native import PostgresSourceFixture
from qdrant_security_guard_native import SecurityGuardDatabase,rows,seed_guard_documents,install_guard
from qdrant_security_guard_schema import CHECKS,run_sql_probes
from qdrant_security_guard_races import RACE_CHECKS,NativeSecurityGuardRaceFailure,run_guard_races
from qdrant_security_lock_cases import _snapshot
from runtime_diagnostics import CleanupFailure,describe_error

SETUP_CHECKS=(
    'non_superuser_schema_owner_operator_verified',
    'accepted_three_profile_writer_seeded_exact_owned_histories',
    'full_guard_install_rollback_restored_catalog_roles_and_history',
    'preexisting_guard_role_refused_without_adoption',
    'fourth_guard_migration_committed_by_non_superuser_operator',
)
PROOF_SCOPE='same_transaction_security_guard_sql_only'


async def check(fixture,progress):
    progress['stage']='operator_bootstrap'
    async with SecurityGuardDatabase(fixture,with_attestations=True) as database:
        checks=[SETUP_CHECKS[0]]
        progress['stage']='seed'
        datasets=await seed_guard_documents(database)
        baselines={name:await _snapshot(database.admin,value['inputs']) for name,value in datasets.items()}
        checks.append(SETUP_CHECKS[1])
        progress['stage']='migration_install'
        source=await install_guard(database)
        checks.extend(SETUP_CHECKS[2:])
        progress['stage']='restricted_sql_probes'
        observed=await run_sql_probes(database,datasets['guard']['arguments'])
        if observed!=list(CHECKS):raise RuntimeError('guard_sql_probe_result_shape')
        checks.extend(observed)
        progress['stage']='atomic_lock_races'
        observed=await run_guard_races(database,{name:value for name,value in datasets.items() if name!='guard'})
        if observed!=list(RACE_CHECKS):raise RuntimeError('guard_sql_race_result_shape')
        checks.extend(observed)
        progress['stage']='final_catalog_history'
        for name,value in datasets.items():
            if await _snapshot(database.admin,value['inputs'])!=baselines[name]:
                raise RuntimeError('guard_sql_immutable_history_changed')
        history=await rows(database.admin,'SELECT version,checksum_sha256 FROM cragkit_qdrant.schema_migrations ORDER BY version LIMIT 5')
        if len(history)!=4 or tuple(history[-1])!=(source.version,source.checksum):
            raise RuntimeError('guard_sql_history_profile')
        fingerprint=(await rows(database.admin,catalog_queries()[0]))[0][0]
        return dict(checks=checks,proof_scope=PROOF_SCOPE,migration=dict(version=source.version,checksum_sha256=source.checksum),
            history=[list(row) for row in history],catalog_fingerprint=fingerprint,
            query_sha256=sha256(catalog_queries()[0].encode('utf-8')).hexdigest(),
            catalog=json.loads((await rows(database.admin,catalog_queries()[1]))[0][0]))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin',type=Path,required=True)
    parser.add_argument('--artifacts-dir',type=Path,required=True)
    parser.add_argument('--allow-local-processes',action='store_true',required=True)
    args=parser.parse_args(argv)
    progress=dict(stage='admission');artifacts_owned=False
    try:
        if args.artifacts_dir.exists():raise RuntimeError('guard_sql_fresh_artifacts_required')
        args.artifacts_dir.mkdir(mode=0o700,parents=True);artifacts_owned=True
        private=Path(tempfile.mkdtemp(prefix='postgres-',dir=args.artifacts_dir)).resolve()
        with PostgresSourceFixture(args.postgres_bin,private/'server',max_connections=6) as fixture:
            result=asyncio.run(asyncio.wait_for(check(fixture,progress),180))
        shutil.rmtree(private)
        result=dict(ok=True,**result,cleanup_verified=True)
        (args.artifacts_dir/'results.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(dict(ok=True,checks=len(result['checks']),proof_scope=PROOF_SCOPE,cleanup_verified=True)))
        return 0
    except Exception as error:
        primary=getattr(error,'primary',None) if isinstance(error,NativeSecurityGuardRaceFailure) else None
        diagnostic=error.to_dict() if isinstance(error,CleanupFailure) else describe_error(primary or error,operation='primary',stage='recovery')
        if artifacts_owned:
            import traceback
            locations=[]
            root=Path(__file__).resolve().parents[1]
            for frame in traceback.extract_tb((primary or error).__traceback__):
                try:relative=Path(frame.filename).resolve().relative_to(root)
                except ValueError:continue
                if relative.parts[0] in ('tools','packages'):locations.append(dict(path=str(relative),line=frame.lineno))
            try:(args.artifacts_dir/'failure-locations.json').write_text(json.dumps(locations)+'\n')
            except Exception:pass
        print(json.dumps(dict(ok=False,stage=progress['stage'],error=diagnostic,
            **({'native':error.observation} if isinstance(error,NativeSecurityGuardRaceFailure) else {}))))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
