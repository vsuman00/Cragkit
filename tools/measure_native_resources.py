"""RST-r1 opt-in local native workload launcher; no model calls or downloads."""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import socket
import sys

from check_qdrant_writer import read_bounded
from measure_default_resources import SAFE_ENV, distribution, pressure_guard
from postgres_vector_fixture import V6PostgresFixture

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CHECKS = frozenset(('ingestion_fidelity', 'evidence_scope', 'evidence_spans',
    'usage_limits', 'strict_tokens', 'deadlines', 'overload_refused', 'queued_cancelled',
    'active_cancelled', 'reuse_after_queue', 'reuse_after_active', 'cleanup_verified'))
WORKER_STAGES = frozenset(('sdk', 'configuration', 'ingestion', 'reader_open',
    'retrieval_one', 'retrieval_two', 'contention', 'active_dispatch', 'active_cancel', 'active_reuse'))
WORKER_CATEGORIES = frozenset(('unknown', 'invalid_request', 'provider_unavailable',
    'deadline_exceeded', 'integrity_violation'))


class NativeResourceError(ValueError):
    """Fixed content-free diagnostic."""


def require(condition):
    if not condition:
        raise NativeResourceError('native_resource_check_failed')


def positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def validate_observation(value, runtime, targets):
    require(type(value) is dict and value.get('revision') == 'RST-r1' and value.get('runtime') == runtime)
    required = {'revision', 'runtime', 'version', 'ingestion_ms', 'retrieval', 'checks',
                'peak_rss_bytes', 'provider_http_calls', 'active_dispatch_observation', 'database_logical_bytes'}
    optional = {'recovery_attempts', 'recovery_refusals', 'recovery_elapsed_ms'} if runtime == 'node' else set()
    require(required <= value.keys() <= required | optional)
    require(value.get('version') == {'python':'1.0.0rc1', 'node':'1.0.0-rc.1'}.get(runtime))
    require(value.get('provider_http_calls') == 0 and type(value['provider_http_calls']) is int)
    require(type(value.get('peak_rss_bytes')) is int and 0 < value['peak_rss_bytes'] < 2**53)
    require(type(value.get('checks')) is dict and REQUIRED_CHECKS == value['checks'].keys()
            and all(type(k) is str and type(v) is bool and v for k, v in value['checks'].items()))
    require(type(value['active_dispatch_observation']) is int and value['active_dispatch_observation'] == 1)
    require(type(value['database_logical_bytes']) is int and 0 < value['database_logical_bytes'] < 2**53)
    if runtime == 'node':
        require(optional <= value.keys() and type(value['recovery_attempts']) is int
                and 1 <= value['recovery_attempts'] <= 25
                and type(value['recovery_refusals']) is int
                and value['recovery_refusals'] == value['recovery_attempts']-1
                and positive(value['recovery_elapsed_ms']) and value['recovery_elapsed_ms'] < 5000)
    require(type(value.get('ingestion_ms')) is list and len(value['ingestion_ms']) == 3)
    distribution(value['ingestion_ms'])
    require(type(value.get('retrieval')) is list and len(value['retrieval']) == 2)
    for concurrency, stage in enumerate(value['retrieval'], 1):
        require(type(stage) is dict and type(stage.get('concurrency')) is int
                and stage['concurrency'] == concurrency and positive(stage.get('elapsed_ms')))
        require(set(stage) == {'concurrency','elapsed_ms','latency_ms','context_tokens','attempts',
                              'provider_calls','throughput_per_second'})
        require(positive(stage['throughput_per_second']))
        require(type(stage.get('latency_ms')) is list and len(stage['latency_ms']) == 20)
        measured = distribution(stage['latency_ms'])
        require(measured['p95'] <= targets['retrieval_p95_deadline_ms'])
        for field, limit in (('context_tokens', 20000), ('attempts', 3), ('provider_calls', 8)):
            require(type(stage.get(field)) is list and len(stage[field]) == 20
                    and all(type(n) is int and 0 <= n <= limit for n in stage[field]))
        # Compute in the parent from raw observations; do not trust a child p95.
        stage['latency_summary_ms'] = measured
        stage['observed_requests_per_second'] = 20000/stage['elapsed_ms']
    value['ingestion_summary_ms'] = distribution(value['ingestion_ms'])
    return value


async def child(argv, configuration=None, *, timeout=180, pressures=None):
    process = await asyncio.create_subprocess_exec(*argv,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={k:os.environ[k] for k in SAFE_ENV if k in os.environ})
    output = asyncio.create_task(read_bounded(process.stdout, 131072))
    errors = asyncio.create_task(read_bounded(process.stderr, 16384))
    async def monitor():
        while True:
            await asyncio.sleep(1)
            pressure_guard(pressures)
    watcher = asyncio.create_task(monitor()) if pressures is not None else None
    streams = asyncio.gather(output, errors)
    try:
        async with asyncio.timeout(timeout):
            if configuration is not None:
                raw = json.dumps(configuration, allow_nan=False).encode()
                require(len(raw) <= 32768)
                process.stdin.write(raw)
                await process.stdin.drain()
            process.stdin.close()
            if watcher is not None:
                done, _ = await asyncio.wait((streams, watcher), return_when=asyncio.FIRST_COMPLETED)
                if watcher in done:
                    await watcher  # A pressure failure stops and reaps the child.
            raw, stderr = await streams
            await process.wait()
        if process.returncode != 0:
            error = NativeResourceError('native_resource_child_failed')
            try:
                diagnostic = json.loads(raw)
                if (type(diagnostic) is dict and set(diagnostic) == {'stage', 'category'}
                        and diagnostic['stage'] in WORKER_STAGES and diagnostic['category'] in WORKER_CATEGORIES):
                    error.worker_diagnostic = diagnostic
            except (ValueError, TypeError):
                pass
            raise error
        require(not stderr)
        return json.loads(raw)
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except TimeoutError:
                process.kill()
                await asyncio.wait_for(process.wait(), 5)
        jobs = (output, errors, streams) + ((watcher,) if watcher is not None else ())
        for task in jobs:
            if not task.done():
                task.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)


async def execute(fixture, runtime, candidate, pressures):
    roles = await fixture.provision(tenants=('resource-tenant',), collections=('resource-tests',))
    configuration = dict(reader_config=roles.reader, writer_config=roles.writer,
        tokenizer_path=str(candidate/'artifacts/tokenizers/cl100k_base.tiktoken'),
        sdk_root=str(candidate/'packages/typescript'))
    if runtime == 'python':
        script = ('import sys,json,asyncio; sys.path.insert(0,sys.argv[1]); '
                  'from resource_workload import run_resource_workload; '
                  'print(json.dumps(asyncio.run(run_resource_workload(json.load(sys.stdin))),allow_nan=False))')
        argv = [str(candidate/'packages/python/.venv/bin/python'), '-I', '-B', '-c', script, str(ROOT/'tools')]
    else:
        script = ("import {pathToFileURL} from 'node:url';"
                  "const {runResourceWorkload}=await import(pathToFileURL(process.argv[1]));"
                  "let data='';for await(const part of process.stdin){data+=part;if(data.length>32768)throw Error('config_limit');}"
                  "try{console.log(JSON.stringify(await runResourceWorkload(JSON.parse(data))));}"
                  "catch(error){console.log(JSON.stringify({stage:error?.stage,category:error?.category}));process.exitCode=1;}")
        argv = ['node', '--input-type=module', '-e', script, str(ROOT/'tools/resource_workload.mjs')]
    observation = await child(argv, configuration, pressures=pressures)
    # Measure database storage separately; never combine it with process RSS.
    import psycopg
    async with await psycopg.AsyncConnection.connect(
        **{k:v for k,v in fixture.config.items() if k != 'max_size'}, sslmode='verify-full',
        connect_timeout=5, options='-c statement_timeout=5000') as connection:
        row = await (await connection.execute('SELECT pg_database_size(current_database())')).fetchone()
        require(row is not None and type(row[0]) is int and row[0] > 0)
        observation['database_logical_bytes'] = row[0]
    return observation


def run(candidate, receipt, prepared_bin, output):
    require(not output.exists())
    output.mkdir(mode=0o700, parents=True)
    configuration = json.loads((candidate/'evaluation/release/V6-candidate.json').read_text())
    observations, pressures = [], []
    verify = [str(candidate/'packages/python/.venv/bin/python'), '-B',
              str(candidate/'tools/evaluation_runtime.py'), 'verify', '--receipt', str(receipt)]
    phase = 'runtime_verify_before'
    try:
        pressure_guard(pressures)
        asyncio.run(child(verify, timeout=90))
        for runtime in ('python', 'node'):
            phase = runtime + '_fixture'
            pressure_guard(pressures)
            with V6PostgresFixture(prepared_bin, output/runtime) as fixture:
                host, port = fixture.config['host'], fixture.config['port']
                phase = runtime + '_workload'
                value = asyncio.run(execute(fixture, runtime, candidate, pressures))
                phase = runtime + '_validation'
                observation = validate_observation(value, runtime, configuration['resource_targets'])
            try:
                connection = socket.create_connection((host, port), timeout=.2)
            except ConnectionRefusedError:
                pass
            else:
                connection.close()
                raise NativeResourceError('native_resource_listener_remains')
            observations.append(observation)
            with (output/(runtime+'-results.json')).open('x') as stream:
                json.dump(observation, stream, indent=2, allow_nan=False)
                stream.write('\n')
            pressure_guard(pressures)
        phase = 'runtime_verify_after'
        asyncio.run(child(verify, timeout=90))
        record = dict(revision='RST-r1', state='passed', evidence_kind='local_postgres_fake_providers',
            runtime_receipt_sha256=sha256(receipt.read_bytes()).hexdigest(),
            tools_sha256={name:sha256((ROOT/'tools'/name).read_bytes()).hexdigest() for name in
                ('resource_workload.py','resource_workload.mjs','measure_native_resources.py')},
            observations=observations, pressure=pressures, cleanup_verified=True,
            live_provider_calls=0, held_out_opened=False)
        with (output/'results.json').open('x') as stream:
            json.dump(record, stream, indent=2, allow_nan=False)
            stream.write('\n')
        return record
    except BaseException as error:
        failure = dict(state='failed', code='native_resource_failed', phase=phase, cleanup_verified=False)
        if type(error) is NativeResourceError and hasattr(error, 'worker_diagnostic'):
            failure['worker'] = error.worker_diagnostic
        (output/'failure.json').write_text(json.dumps(failure)+'\n')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-root', type=Path, required=True)
    parser.add_argument('--runtime-receipt', type=Path, required=True)
    parser.add_argument('--prepared-postgres-bin', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-local-processes', action='store_true', required=True)
    args = parser.parse_args()
    try:
        result = run(args.candidate_root.resolve(), args.runtime_receipt.resolve(),
                     args.prepared_postgres_bin.resolve(), args.output.resolve())
        print(json.dumps(dict(state=result['state'], revision='RST-r1')))
        return 0
    except (Exception, KeyboardInterrupt):
        print('native_resource_failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
