"""Opt-in disposable native backend/direct/tool/MCP conformance."""
import argparse
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from check_qdrant_writer import read_bounded
from qdrant_native import REFERENCE_BINARY_SHA256
from qdrant_authority_schema import ROOT
from qdrant_source_native import PostgresSourceFixture
from qdrant_publication_native import PublicationDatabase
from v5_conformance_fixture import conformance_input,install_core,cases
from v5_conformance_python import CHECKS


def validate_result(value,runtime):
    if (type(value) is not dict or set(value)!={'runtime','checks','route_calls','boundary_refusals','observations','cleanup_verified'}
            or value['runtime']!=runtime or value['checks']!=list(CHECKS) or value['route_calls']!=42
            or value['boundary_refusals']!=8 or value['cleanup_verified'] is not True or type(value['observations']) is not list or len(value['observations'])!=14):
        raise RuntimeError('v5_conformance_result_shape')
    from cragkit.contracts import parse_result
    inputs=conformance_input();base=inputs['base'];manifest=base['manifest'];canonical=base['canonical_text'].encode()
    identifiers=('unknown','sufficient','partial','no_match','foreign_document','partial_generation','provider_budget')
    expected=[(profile,name) for profile in ('postgres_lexical','qdrant_dense') for name in identifiers]
    actual=[]
    for row in value['observations']:
        if type(row) is not dict or set(row)!={'profile','case','result'}:raise RuntimeError('v5_conformance_observation_shape')
        result=parse_result(row['result'])
        expected_status='sufficient' if row['case']=='sufficient' else 'insufficient' if row['case'] in ('no_match','foreign_document','partial_generation') or row['profile']=='qdrant_dense' and row['case']=='provider_budget' else 'partial'
        expected_calls=1 if row['profile']=='qdrant_dense' and row['case']!='provider_budget' else 0
        if result.request_id!=row['case'] or result.status!=expected_status or result.execution!='complete':raise RuntimeError('v5_conformance_status')
        if result.usage.provider_calls!=expected_calls or result.usage.attempt_count!=1 or result.usage.context_tokens+128>2000:raise RuntimeError('v5_conformance_budget')
        for evidence in result.evidence:
            if (evidence.document_id!=manifest['document_id'] or evidence.revision_id!=manifest['revision_id']
                    or evidence.source_sha256!=manifest['source_sha256']
                    or evidence.text!=canonical[evidence.start_byte:evidence.end_byte].decode()):raise RuntimeError('v5_conformance_source_identity')
        actual.append((row['profile'],row['case']))
    if actual!=expected:raise RuntimeError('v5_conformance_observation_membership')
    return value


async def check(fixture,runtime,binary,work):
    async with PublicationDatabase(fixture,with_attestations=True) as database:
        inputs=conformance_input();postgres=await install_core(database,inputs)
        inputs['cases']=cases(inputs)
        value=dict(binary=str(binary),work_dir=str(work),inputs=inputs,postgres_config=postgres,
            writer_config=database.config('writer'),supervisor_config=database.config('supervisor'),reader_config=database.config('reader'))
        await database.release_admin()
        environment={key:val for key,val in os.environ.items() if not key.startswith(('PG','QDRANT__','LANGCHAIN','LANGSMITH','OTEL_'))
            and key not in ('NODE_OPTIONS','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NODE_USE_ENV_PROXY')}
        command=[sys.executable,str(ROOT/'tools/v5_conformance_python.py')] if runtime=='python' else ['node',str(ROOT/'tools/check_typescript_v5_conformance.mjs')]
        process=await asyncio.create_subprocess_exec(*command,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,env=environment,start_new_session=True)
        output=asyncio.create_task(read_bounded(process.stdout,262144));errors=asyncio.create_task(read_bounded(process.stderr,65536))
        try:
            process.stdin.write(json.dumps(value,ensure_ascii=False).encode());await process.stdin.drain();process.stdin.close()
            async with asyncio.timeout(150):
                stdout,stderr=await asyncio.gather(output,errors);await process.wait()
            result=json.loads(stdout)
            if process.returncode or stderr:
                (work.parent/'failure.json').write_text(json.dumps(result)+'\n')
                raise RuntimeError('v5_conformance_native_failed')
            return validate_result(result,runtime)
        finally:
            if process.returncode is None:
                process.terminate()
                try:await asyncio.wait_for(process.wait(),10)
                except TimeoutError:process.kill();await process.wait()
            for job in (output,errors):
                if not job.done():job.cancel()
            await asyncio.gather(output,errors,return_exceptions=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin',type=Path,required=True)
    parser.add_argument('--server-binary',type=Path,required=True)
    parser.add_argument('--binary-sha256',required=True)
    parser.add_argument('--artifacts-dir',type=Path,required=True)
    parser.add_argument('--runtime',choices=('python','typescript','all'),default='all')
    parser.add_argument('--allow-local-processes',action='store_true',required=True)
    args=parser.parse_args()
    try:
        binary=args.server_binary.resolve(strict=True)
        if args.binary_sha256!=REFERENCE_BINARY_SHA256 or sha256(binary.read_bytes()).hexdigest()!=REFERENCE_BINARY_SHA256:
            raise RuntimeError('v5_conformance_binary_profile')
        if args.artifacts_dir.exists():raise RuntimeError('v5_conformance_fresh_artifacts')
        args.artifacts_dir.mkdir(parents=True,mode=0o700);results=[]
        for runtime in ('python','typescript') if args.runtime=='all' else (args.runtime,):
            private=Path(tempfile.mkdtemp(prefix=runtime+'-',dir=args.artifacts_dir)).resolve()
            with PostgresSourceFixture(args.postgres_bin,private/'postgres',max_connections=6) as fixture:
                result=asyncio.run(check(fixture,runtime,binary,private/'managed'))
            shutil.rmtree(private);results.append(result)
        if len(results)==2 and results[0]['observations']!=results[1]['observations']:
            raise RuntimeError('v5_conformance_runtime_parity')
        (args.artifacts_dir/'results.json').write_text(json.dumps(dict(ok=True,results=results,cleanup_verified=True),indent=2,ensure_ascii=False)+'\n')
        print(json.dumps(dict(ok=True,route_calls=sum(result['route_calls'] for result in results),cleanup_verified=True)))
        return 0
    except Exception as error:
        print(json.dumps(dict(ok=False,error=type(error).__name__)))
        return 1


if __name__=='__main__':raise SystemExit(main())
