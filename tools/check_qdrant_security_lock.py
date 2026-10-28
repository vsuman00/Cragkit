"""Opt-in disposable SQL counterexample for separate-connection lock custody."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import shutil
import tempfile

from qdrant_publication_native import PublicationDatabase
from qdrant_source_native import PostgresSourceFixture
from qdrant_security_lock_cases import CHECKS,NativeSecurityLockFailure,run_security_lock_cases
from runtime_diagnostics import CleanupFailure,describe_error

PROOF_SCOPE='two_connection_guard_counterexample_sql_only'


async def check(fixture):
    async with PublicationDatabase(fixture,with_attestations=True) as database:
        async with asyncio.timeout(60):
            observed=await run_security_lock_cases(database)
        if type(observed) is not list or observed!=list(CHECKS):
            raise RuntimeError('security_lock_counterexample_result_shape')
        return observed


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin',type=Path,required=True)
    parser.add_argument('--artifacts-dir',type=Path,required=True)
    parser.add_argument('--allow-local-processes',action='store_true',required=True)
    args=parser.parse_args(argv)
    try:
        if args.artifacts_dir.exists():
            raise RuntimeError('security_lock_counterexample_fresh_artifacts_required')
        args.artifacts_dir.mkdir(mode=0o700,parents=True)
        private=Path(tempfile.mkdtemp(prefix='postgres-',dir=args.artifacts_dir)).resolve()
        # Two restricted runtime clients plus one administrative barrier observer.
        with PostgresSourceFixture(args.postgres_bin,private/'server',max_connections=6) as fixture:
            observed=asyncio.run(check(fixture))
        shutil.rmtree(private)
        result=dict(ok=True,checks=observed,proof_scope=PROOF_SCOPE,counterexample_observed=True,cleanup_verified=True)
        (args.artifacts_dir/'results.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(dict(ok=True,checks=len(observed),proof_scope=PROOF_SCOPE,counterexample_observed=True,cleanup_verified=True)))
        return 0
    except Exception as error:
        diagnostic=error.to_dict() if isinstance(error,CleanupFailure) else describe_error(error,operation='primary',stage='recovery')
        print(json.dumps(dict(ok=False,error=diagnostic,
            **({'native':error.observation} if isinstance(error,NativeSecurityLockFailure) else {}))))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
