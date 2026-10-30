"""Opt-in actual managed purge acceptance on disposable PostgreSQL and Qdrant."""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import signal
import tempfile
import traceback

from check_qdrant_writer import read_bounded
from qdrant_native import REFERENCE_BINARY_SHA256
from qdrant_purge_cases import CHECKS, FAULT_CHECKS, COMPLETED, POLICY, NativePurgeFailure, purge_input
from qdrant_purge_native import install
from qdrant_security_guard_native import SecurityGuardDatabase, install_guard
from qdrant_source_native import PostgresSourceFixture
from runtime_diagnostics import describe_error

ROOT = Path(__file__).resolve().parents[1]
ERRORS = frozenset(('InvalidRequest', 'IntegrityViolation', 'ProviderUnavailable', 'UnauthorizedScope',
    'UnsupportedCapability', 'DeadlineExceeded', 'IndexNotReady', 'BudgetExhausted', 'AbortError', 'internal'))


def validate_result(value, runtime):
    if (type(value) is not dict or set(value) != {'runtime', 'checks', 'fault_checks', 'proof_scope', 'semantic_witness_sha256'}
            or value['runtime'] != runtime or value['checks'] != list(CHECKS)
            or value['fault_checks'] != list(FAULT_CHECKS)
            or value['proof_scope'] != 'native_managed_purge_only'
            or type(value['semantic_witness_sha256']) is not str
            or re.fullmatch('[0-9a-f]{64}', value['semantic_witness_sha256']) is None):
        raise RuntimeError('purge_native_result_shape')
    return json.loads(json.dumps(value))


async def node_cases(value):
    environment = {key: item for key, item in os.environ.items()
        if not key.startswith(('PG', 'QDRANT__'))
        and key not in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NODE_OPTIONS', 'NODE_USE_ENV_PROXY', 'RUST_LOG')}
    process = await asyncio.create_subprocess_exec('node', str(ROOT/'tools/check_typescript_qdrant_purge.mjs'),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=environment, start_new_session=True, limit=65536)
    output = asyncio.create_task(read_bounded(process.stdout, 65536))
    errors = asyncio.create_task(read_bounded(process.stderr, 65536))
    try:
        async with asyncio.timeout(220):
            process.stdin.write(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())
            await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()
            stdout, stderr = await asyncio.gather(output, errors)
            await process.wait()
        if process.returncode != 0 and not stderr:
            observed = json.loads(stdout)
            if (type(observed) is not dict or set(observed) != {'ok', 'step', 'error'}
                    or observed['ok'] is not False or type(observed['step']) is not int
                    or not 0 <= observed['step'] <= len(CHECKS) or observed['error'] not in ERRORS):
                raise RuntimeError('purge_native_failure_shape')
            raise NativePurgeFailure(observed)
        if process.returncode != 0 or stderr:
            raise RuntimeError('purge_native_child_failed')
        return validate_result(json.loads(stdout), 'typescript')
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except TimeoutError:
                os.killpg(process.pid, signal.SIGKILL)
                await asyncio.wait_for(process.wait(), 3)
        for task in (output, errors):
            if not task.done():
                task.cancel()
        await asyncio.gather(output, errors, return_exceptions=True)


async def storage_checks(database, inputs):
    """Observe actual retained identities and erased bodies without runtime RLS."""
    from cragkit._qdrant_manifest import encode_purge_intent
    from cragkit._qdrant_writer_contract import prepare_stage, stage_data

    connection = await database._connect(database.fixture.config)
    checks = []
    try:
        async with connection.transaction():
            await connection.execute('SET TRANSACTION READ ONLY')
            await connection.execute('SET LOCAL search_path=pg_catalog')
            async def rows(sql, keys):
                return await (await connection.execute(sql, keys, prepare=False)).fetchall()
            for name, fixture in inputs['documents'].items():
                erased = name in COMPLETED
                outside = name == 'outside_replacement'
                first = fixture['stage']['manifest']
                key = (first['tenant_id'], first['collection'], first['document_id'])
                where = 'tenant_id=%s AND collection=%s AND document_id=%s'
                stages = [fixture['stage']] + ([] if name == 'ownerless' else [fixture['second_stage']])
                graphs = [stage_data(prepare_stage(stage)) for stage in stages]
                expected_revisions, expected_members, expected_claims, expected_replays, groups = [], [], [], [], []
                for graph in graphs:
                    manifest = graph.manifest
                    expected_revisions.append((manifest.revision_id, manifest.source_sha256, len(graph.source), erased, erased))
                    for index, member in enumerate(manifest.members):
                        expected_members.append((manifest.revision_id, manifest.generation_id, member.chunk_id,
                            member.point_id, member.start_byte, member.end_byte, member.text_sha256,
                            manifest.source_sha256, member.end_byte-member.start_byte, erased, erased))
                        dense, sparse = graph.dense[index], graph.sparse[index]
                        expected_replays.append((member.point_id, dense.blob_sha256,
                            len(dense.blob), sparse.blob_sha256 if sparse else None,
                            len(sparse.blob) if sparse else None, erased, erased if sparse else True, erased))
                        expected_claims.append((member.point_id, manifest.revision_id, manifest.generation_id,
                            member.chunk_id, member.start_byte, member.end_byte, manifest.source_sha256,
                            member.text_sha256, dense.input_sha256, sparse.input_sha256 if sparse else None))
                    groups.append([manifest.revision_id, manifest.generation_id, graph.manifest_encoding.sha256,
                        sorted(member.point_id for member in manifest.members)])
                actual = await rows('SELECT revision_id,source_sha256,canonical_original_bytes,canonical_utf8 IS NULL,content_erased '
                    'FROM cragkit_qdrant.document_revisions WHERE '+where+' ORDER BY revision_id', key)
                if actual != sorted(expected_revisions):
                    raise RuntimeError('purge_native_revision_metadata')
                actual = await rows('SELECT revision_id,generation_id,chunk_id,point_id::text,start_byte,end_byte,text_sha256,'
                    'source_sha256,excerpt_original_bytes,excerpt_utf8 IS NULL,content_erased FROM cragkit_qdrant.members WHERE '+
                    where+' ORDER BY revision_id,generation_id,chunk_id', key)
                if actual != sorted(expected_members):
                    raise RuntimeError('purge_native_member_metadata')
                actual = await rows('SELECT point_id::text,dense_blob_sha256,dense_original_bytes,'
                    'sparse_blob_sha256,sparse_original_bytes,dense_blob IS NULL,sparse_blob IS NULL,content_erased '
                    'FROM cragkit_qdrant.vector_replays WHERE '+where+' ORDER BY point_id', key)
                if actual != sorted(expected_replays):
                    raise RuntimeError('purge_native_replay_metadata')
                actual = await rows('SELECT point_id::text,revision_id,generation_id,chunk_id,start_byte,end_byte,source_sha256,'
                    'text_sha256,dense_input_sha256,sparse_input_sha256 FROM cragkit_qdrant.point_claims WHERE '+where+' ORDER BY point_id', key)
                if actual != sorted(expected_claims):
                    raise RuntimeError('purge_native_claim_metadata')
                actual = await rows('SELECT count(*),bool_and(content_erased),bool_and(request_bytes IS NULL),'
                    "bool_and(request_original_bytes>0 AND request_sha256 ~ '^[0-9a-f]{64}$') "
                    'FROM cragkit_qdrant.dispatch_journal WHERE '+where, key)
                if len(actual) != 1 or actual[0][0] < 1 or actual[0][1:] != (erased, erased, True):
                    raise RuntimeError('purge_native_request_erasure')
                actual = await rows('SELECT content_unavailable,tombstoned,active_generation_id '
                    'FROM cragkit_qdrant.documents WHERE '+where, key)
                active = None if name == 'ownerless' else (fixture['second_stage']['manifest']['generation_id']
                    if fixture.get('published_second') else first['generation_id'])
                if actual != [(erased, not outside, active)]:
                    raise RuntimeError('purge_native_document_barrier')
                if outside:
                    actual = await rows('SELECT count(*) FROM cragkit_qdrant.publication_intents WHERE '+where+
                        " AND action IN ('tombstone','purge')", key)
                    if actual != [(0,)]:
                        raise RuntimeError('purge_native_outside_authority_changed')
                else:
                    terminal = fixture.get('followup_purge', fixture['purge'])
                    actual = await rows('SELECT state,authority_committed,replica_complete,purge_complete,payload_sha256 '
                        'FROM cragkit_qdrant.publication_intents WHERE '+where+' AND intent_id=%s', (*key, terminal['intent_id']))
                    digest = encode_purge_intent(terminal).sha256
                    if erased and actual != [('complete', True, True, True, digest)]:
                        raise RuntimeError('purge_native_terminal_flags')
                    if not erased and (len(actual) != 1 or actual[0][2:4] != (False, False)):
                        raise RuntimeError('purge_native_refusal_flags')
                records = await rows('SELECT policy_id,purge_payload_sha256,tombstone_payload_sha256,inventory_sha256,'
                    'absence_sha256,erasure_sha256 FROM cragkit_qdrant.purge_erasures WHERE '+where, key)
                if erased:
                    inventory = ['cragkit.qdrant.security-inventory.v1', inputs['config']['backend_namespace'],
                        inputs['config']['physical_collection'], inputs['config']['collection_incarnation'], *key,
                        inputs['instance_id'], sorted(groups)]
                    inventory_hash = sha256(json.dumps(inventory, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
                    if (len(records) != 1 or records[0][:4] != (POLICY, digest,
                            terminal['tombstone_intent_payload_sha256'], inventory_hash)
                            or any(re.fullmatch('[0-9a-f]{64}', item) is None for item in records[0][4:])):
                        raise RuntimeError('purge_native_erasure_record')
                elif records:
                    raise RuntimeError('purge_native_refusal_erasure_record')
                if 'followup_purge' in fixture:
                    original = await rows('SELECT replica_complete,purge_complete FROM cragkit_qdrant.publication_intents WHERE '+where+' AND intent_id=%s',
                        (*key, fixture['purge']['intent_id']))
                    if original != [(False, False)]:
                        raise RuntimeError('purge_native_stale_authority_completed')
                checks.append(name+'_original_identity_and_managed_body_state')
        return checks
    finally:
        await connection.close()


async def check(fixture, runtime, binary, work_dir):
    async with SecurityGuardDatabase(fixture, with_attestations=True) as database:
        await install_guard(database)
        await install(database)
        inputs = purge_input()
        value = dict(binary=str(binary), work_dir=str(work_dir), inputs=inputs,
            writer_config=database.config('writer'), supervisor_config=database.config('supervisor'),
            reader_config=database.config('reader'), admin_config=database.fixture.config)
        await database.release_admin()
        if runtime == 'python':
            from qdrant_purge_cases import python_purge_cases
            result = await python_purge_cases(value)
        else:
            result = await node_cases(value)
        result = validate_result(result, runtime)
        return dict(result=result, storage_checks=await storage_checks(database, inputs))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin', type=Path, required=True)
    parser.add_argument('--server-binary', type=Path, required=True)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--artifacts-dir', type=Path, required=True)
    parser.add_argument('--runtime', choices=('python', 'typescript', 'all'), default='all')
    parser.add_argument('--allow-local-processes', action='store_true', required=True)
    args = parser.parse_args(argv)
    artifacts_owned = False
    try:
        binary = args.server_binary.resolve(strict=True)
        if (args.binary_sha256 != REFERENCE_BINARY_SHA256 or not os.access(binary, os.X_OK)
                or sha256(binary.read_bytes()).hexdigest() != REFERENCE_BINARY_SHA256):
            raise RuntimeError('purge_native_binary_profile')
        if args.artifacts_dir.exists():
            raise RuntimeError('purge_native_fresh_artifacts_required')
        args.artifacts_dir.mkdir(parents=True, mode=0o700)
        artifacts_owned = True
        observations = []
        for runtime in ('python', 'typescript') if args.runtime == 'all' else (args.runtime,):
            private = Path(tempfile.mkdtemp(prefix=runtime+'-', dir=args.artifacts_dir)).resolve()
            with PostgresSourceFixture(args.postgres_bin, private/'postgres', max_connections=7) as fixture:
                result = asyncio.run(asyncio.wait_for(check(fixture, runtime, binary, private/'managed'), 240))
            shutil.rmtree(private)
            observations.append(result)
            (args.artifacts_dir/(runtime+'-results.json')).write_text(json.dumps(result, indent=2)+'\n')
        if len({item['result']['semantic_witness_sha256'] for item in observations}) != 1:
            raise RuntimeError('purge_native_semantic_parity')
        result = dict(ok=True, observations=observations, cleanup_verified=True)
        (args.artifacts_dir/'results.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(dict(ok=True, checks=sum(len(item['result']['checks'])+len(item['result']['fault_checks'])+len(item['storage_checks'])
            for item in observations), cleanup_verified=True)))
        return 0
    except Exception as error:
        primary = getattr(error, 'primary', None) or error
        if artifacts_owned:
            locations = []
            for frame in traceback.extract_tb(primary.__traceback__):
                try:
                    path = Path(frame.filename).resolve().relative_to(ROOT)
                except ValueError:
                    continue
                if path.parts[0] in ('tools', 'packages'):
                    locations.append(dict(path=str(path), line=frame.lineno))
            (args.artifacts_dir/'failure-locations.json').write_text(json.dumps(locations)+'\n')
        print(json.dumps(dict(ok=False, error=describe_error(primary, operation='primary', stage='recovery'),
            **({'native': error.observation} if isinstance(error, NativePurgeFailure) else {}))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
