"""Opt-in native profile-4 writer admission and committed metadata drift."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import signal
import tempfile

from check_qdrant_writer import read_bounded
from qdrant_authority_schema import ROOT
from qdrant_guard_writer_cases import failure_observation
from qdrant_guard_writer_cases import CHECKS,NativeGuardWriterFailure,writer_inputs,python_guard_writer_cases
from qdrant_security_guard_native import SecurityGuardDatabase,seed_guard_documents,install_guard
from qdrant_source_native import PostgresSourceFixture
from runtime_diagnostics import CleanupFailure,describe_error


def validate_result(value,runtime):
    if (type(value) is not dict or set(value)!={'runtime','checks','proof_scope','scope_queries','denied_scope_queries'}
            or type(value['runtime']) is not str or value['runtime']!=runtime
            or type(value['checks']) is not list or any(type(item) is not str for item in value['checks']) or value['checks']!=list(CHECKS)
            or type(value['proof_scope']) is not str or value['proof_scope']!='profile4_writer_admission_only'
            or type(value['scope_queries']) is not int or value['scope_queries']!=6
            or type(value['denied_scope_queries']) is not int or value['denied_scope_queries']!=0):
        raise RuntimeError('guard_writer_native_result_shape')
    return json.loads(json.dumps(value))


async def node_cases(value):
    env={key:item for key,item in os.environ.items() if not key.startswith(('PG','QDRANT__'))
        and key not in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NODE_OPTIONS','NODE_USE_ENV_PROXY','RUST_LOG')}
    child=await asyncio.create_subprocess_exec('node',str(ROOT/'tools/check_typescript_qdrant_guard_writer.mjs'),
        stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
        env=env,start_new_session=True,limit=65536)
    output=asyncio.create_task(read_bounded(child.stdout,65536));errors=asyncio.create_task(read_bounded(child.stderr,65536))
    try:
        async with asyncio.timeout(150):
            child.stdin.write(json.dumps(value,separators=(',',':')).encode());await child.stdin.drain()
            child.stdin.close();await child.stdin.wait_closed()
            stdout,stderr=await asyncio.gather(output,errors);code=await child.wait()
        if code and not stderr:raise NativeGuardWriterFailure(failure_observation(json.loads(stdout)))
        if code or stderr:raise RuntimeError('guard_writer_native_child_failed')
        return validate_result(json.loads(stdout),'typescript')
    finally:
        if child.returncode is None:
            child.terminate()
            try:await asyncio.wait_for(child.wait(),5)
            except TimeoutError:
                os.killpg(child.pid,signal.SIGKILL);await asyncio.wait_for(child.wait(),2)
        for task in (output,errors):
            if not task.done():task.cancel()
        await asyncio.gather(output,errors,return_exceptions=True)


async def check(fixture,runtime):
    async with SecurityGuardDatabase(fixture,with_attestations=True) as database:
        datasets=await seed_guard_documents(database)
        await install_guard(database)
        value=dict(writer_config=database.config('writer'),operator_config=dict(database._operator_config),
            inputs=writer_inputs(datasets['guard']))
        run=python_guard_writer_cases if runtime=='python' else node_cases
        return validate_result(await run(value),runtime)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin',type=Path,required=True)
    parser.add_argument('--artifacts-dir',type=Path,required=True)
    parser.add_argument('--runtime',choices=('python','typescript','all'),default='all')
    parser.add_argument('--allow-local-processes',action='store_true',required=True)
    args=parser.parse_args(argv)
    artifacts_owned=False
    try:
        if args.artifacts_dir.exists():raise RuntimeError('guard_writer_native_fresh_artifacts')
        args.artifacts_dir.mkdir(mode=0o700,parents=True);artifacts_owned=True
        results=[]
        for runtime in ('python','typescript') if args.runtime=='all' else (args.runtime,):
            private=Path(tempfile.mkdtemp(prefix=runtime+'-',dir=args.artifacts_dir)).resolve()
            with PostgresSourceFixture(args.postgres_bin,private/'server',max_connections=6) as fixture:
                result=asyncio.run(asyncio.wait_for(check(fixture,runtime),175))
            shutil.rmtree(private);results.append(result)
        (args.artifacts_dir/'results.json').write_text(json.dumps(dict(ok=True,results=results,cleanup_verified=True),indent=2)+'\n')
        print(json.dumps(dict(ok=True,checks=sum(len(row['checks']) for row in results),cleanup_verified=True)))
        return 0
    except Exception as error:
        primary=getattr(error,'primary',None) if isinstance(error,NativeGuardWriterFailure) else None
        diagnostic=error.to_dict() if isinstance(error,CleanupFailure) else describe_error(primary or error,operation='primary',stage='recovery')
        if artifacts_owned:
            import traceback
            locations=[]
            for frame in traceback.extract_tb((primary or error).__traceback__):
                try:relative=Path(frame.filename).resolve().relative_to(ROOT)
                except ValueError:continue
                if relative.parts[0] in ('tools','packages'):locations.append(dict(path=str(relative),line=frame.lineno))
            try:(args.artifacts_dir/'failure-locations.json').write_text(json.dumps(locations)+'\n')
            except Exception:pass
        print(json.dumps(dict(ok=False,error=diagnostic,**({'native':error.observation} if isinstance(error,NativeGuardWriterFailure) else {}))))
        return 1


if __name__=='__main__':raise SystemExit(main())
