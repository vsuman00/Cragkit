"""Opt-in five-mode execution on disposable PostgreSQL; synthetic mechanics only."""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import socket
import sys
import shutil

from check_qdrant_writer import read_bounded
from postgres_vector_fixture import V6PostgresFixture

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / 'contracts/fixtures/retrieval_evaluation.json'
MODES = ('lexical', 'dense', 'hybrid', 'reranked_hybrid', 'corrective')
_RECEIPT_FIELDS = {'tenant_id', 'collection', 'document_id', 'logical_revision_id',
                   'revision_id', 'generation_id', 'canonical_sha256', 'embedding_profile', 'active'}


class NativeEvaluationError(ValueError):
    """Closed diagnostics without configuration, provider bodies or query text."""


def require(condition, code):
    if not condition:
        raise NativeEvaluationError(code)


def _identity(document):
    return tuple(document[key] for key in ('tenant_id', 'collection', 'document_id'))


def _matches(condition, document):
    """Independent predicate for this fixture's identity-filter cases."""
    op = condition['op']
    if op in ('and', 'or'):
        values = [_matches(child, document) for child in condition['filters']]
        return all(values) if op == 'and' else any(values)
    if op == 'not':
        return not _matches(condition['filter'], document)
    require(condition.get('field') in ('document_id', 'revision_id'), 'evaluation_filter_scope')
    value = document[condition['field']]
    if op == 'in':
        return value in condition['values']
    require(op in ('eq', 'ne'), 'evaluation_filter_scope')
    return (value == condition['value']) if op == 'eq' else (value != condition['value'])


def validate_observation(packet, observation, runtime, *, counter=None):
    """Validate actual wires against canonical sources, then normalize timing only."""
    from cragkit.contracts import parse_result
    from cragkit.context import Cl100kCounter, count_context
    from cragkit.embeddings import FAKE_PROFILE

    if counter is None:
        counter = Cl100kCounter.from_file(ROOT/'artifacts/tokenizers/cl100k_base.tiktoken')
    require(type(observation) is dict and set(observation) == {
        'revision', 'runtime', 'kind', 'receipts', 'rows', 'cleanup_verified'}, 'evaluation_result_shape')
    require(observation['revision'] == 'EVX-r1' and observation['runtime'] == runtime
            and observation['kind'] == 'mechanics' and observation['cleanup_verified'] is True,
            'evaluation_result_identity')
    documents = {(*_identity(d), d['revision_id']): d for d in packet['documents']}
    require(type(observation['receipts']) is list
            and len(observation['receipts']) == len(documents), 'evaluation_receipt_count')
    ordered = sorted(packet['documents'], key=lambda d: (
        *(part.encode('utf-8') for part in _identity(d)), d['active'], d['revision_id'].encode('utf-8')))
    sources = {}
    for expected, receipt in zip(ordered, observation['receipts'], strict=True):
        require(type(receipt) is dict and set(receipt) == _RECEIPT_FIELDS, 'evaluation_receipt_shape')
        require(all(receipt[key] == expected[key] for key in (*('tenant_id', 'collection', 'document_id'),
                'canonical_sha256', 'active'))
                and receipt['logical_revision_id'] == expected['revision_id']
                and receipt['embedding_profile'] == FAKE_PROFILE.profile_id
                and all(type(receipt[key]) is str and receipt[key] for key in ('revision_id', 'generation_id')),
                'evaluation_receipt_identity')
        key = (*_identity(expected), receipt['revision_id'])
        require(key not in sources, 'evaluation_alias_collision')
        sources[key] = expected
    require(type(observation['rows']) is list and len(observation['rows']) == len(packet['queries'])*5,
            'evaluation_row_count')
    expected_rows = [(query, mode) for query in packet['queries'] for mode in MODES]
    normalized_rows = []
    for (query, mode), row in zip(expected_rows, observation['rows'], strict=True):
        require(type(row) is dict and set(row) == {'question_id', 'mode', 'result', 'latency_ms'},
                'evaluation_row_shape')
        require(row['question_id'] == query['question_id'] and row['mode'] == mode,
                'evaluation_row_order')
        duration = row['latency_ms']
        require(type(duration) in (int, float) and math.isfinite(duration) and 0 <= duration <= 180000,
                'evaluation_latency')
        require(type(row['result']) is dict and not row['result'].get('operational_failure'),
                'evaluation_operational_failure')
        result = parse_result(row['result'])
        require(result.status != 'sufficient' and result.execution == 'complete'
                and result.versions.policy == 'unassessed.v0'
                and all(facet.state == 'unknown' for facet in result.facets), 'evaluation_unknown_coverage')
        usage = result.usage
        require(usage.attempt_count <= 3 and usage.provider_calls <= 8
                and usage.context_counting == 'strict' and usage.context_tokens is not None
                and usage.context_tokens + 256 <= 20000, 'evaluation_request_budget')
        require(usage.cost_kind == 'known' and usage.cost_usd == 0, 'evaluation_fake_cost')
        counted = count_context([item.model_dump(mode='json') for item in result.evidence],
            max_tokens=20000, reserve=256, counter=counter, counting_mode='strict')
        require(result.context == counted['context']
                and usage.context_tokens == counted['context_tokens'], 'evaluation_context_accounting')
        for evidence in result.evidence:
            key = (query['tenant_id'], evidence.collection, evidence.document_id, evidence.revision_id)
            document = sources.get(key)
            require(document is not None and document['active']
                    and evidence.collection == query['collection'], 'evaluation_source_scope')
            raw = document['text'].encode('utf-8')
            require(sha256(raw).hexdigest() == document['canonical_sha256'] == evidence.source_sha256
                    and raw[evidence.start_byte:evidence.end_byte] == evidence.text.encode('utf-8'),
                    'evaluation_source_fidelity')
            require(all(_matches(condition, document) for condition in query['required_filters']),
                    'evaluation_required_filter')
        no_match = query['question_id'] in ('foreign', 'missing', 'historical')
        # pg_catalog.simple does not equate "expiry" in the query with "expire".
        no_match = no_match or (query['question_id'] == 'cache' and mode == 'lexical')
        if no_match:
            require(not result.evidence, 'evaluation_negative_release')
        else:
            require(bool(result.evidence), 'evaluation_positive_missing')
        wire = deepcopy(row['result'])
        for stage in wire['usage']['stage_durations']:
            stage['duration_ms'] = 0
        normalized_rows.append({'question_id': row['question_id'], 'mode': mode, 'result': wire})
    return {'receipts': deepcopy(observation['receipts']), 'rows': normalized_rows}


async def _node(packet, options):
    environment = {key: os.environ[key]
                   for key in ('PATH', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR', 'TZ')
                   if key in os.environ}
    node = shutil.which('node')
    require(node is not None, 'evaluation_node_missing')
    process = await asyncio.create_subprocess_exec(
        str(Path(node).resolve()), str(ROOT/'tools/typescript_retrieval_evaluation.mjs'),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=environment)
    output = asyncio.create_task(read_bounded(process.stdout, 16*1024*1024))
    errors = asyncio.create_task(read_bounded(process.stderr, 65536))
    try:
        async with asyncio.timeout(180):
            process.stdin.write(json.dumps({'packet': packet, 'options': options}, ensure_ascii=False).encode())
            await process.stdin.drain()
            process.stdin.close()
            raw, stderr = await asyncio.gather(output, errors)
            await process.wait()
        require(process.returncode == 0 and not stderr, 'evaluation_node_failed')
        return json.loads(raw)
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except TimeoutError:
                process.kill()
                await asyncio.wait_for(process.wait(), 5)
        for job in (output, errors):
            if not job.done():
                job.cancel()
        await asyncio.gather(output, errors, return_exceptions=True)


async def _execute(fixture, packet, runtime):
    roles = await fixture.provision(
        tenants=tuple(sorted({d['tenant_id'] for d in packet['documents']})),
        collections=tuple(sorted({d['collection'] for d in packet['documents']})))
    options = dict(reader_config=roles.reader, writer_config=roles.writer,
                   tokenizer_path=str(ROOT/'artifacts/tokenizers/cl100k_base.tiktoken'), kind='mechanics')
    async with asyncio.timeout(180):
        if runtime == 'node':
            return await _node(packet, options)
        from retrieval_evaluation import run_evaluation
        return await run_evaluation(packet, **options)


def run(prepared_bin, output):
    require(not output.exists(), 'evaluation_fresh_output_required')
    output.mkdir(parents=True, mode=0o700)
    try:
        return _run(prepared_bin, output)
    except BaseException:
        # Never convert an interrupted/failed run into a passing cleanup claim.
        failure = {'state': 'failed', 'code': 'native_evaluation_failed', 'cleanup_verified': False}
        try:
            (output/'failure.json').write_text(json.dumps(failure)+'\n')
        except OSError:
            pass  # Preserve the pending failure if its diagnostic cannot be saved.
        raise


def _run(prepared_bin, output):
    packet_bytes = PACKET.read_bytes()
    packet = json.loads(packet_bytes)
    observations, views = [], []
    for runtime in ('python', 'node'):
        with V6PostgresFixture(prepared_bin, output/runtime) as fixture:
            host, port = fixture.config['host'], fixture.config['port']
            observation = asyncio.run(_execute(fixture, packet, runtime))
            path = output/f'{runtime}-observations.json'
            path.write_text(json.dumps(observation, ensure_ascii=False, indent=2)+'\n')
            view = validate_observation(packet, observation, runtime)
        try:
            connection = socket.create_connection((host, port), timeout=.2)
        except ConnectionRefusedError:
            pass
        else:
            connection.close()
            raise NativeEvaluationError('evaluation_listener_remains')
        observations.append(dict(runtime=runtime, rows=len(observation['rows']),
            receipts=len(observation['receipts']), sha256=sha256(path.read_bytes()).hexdigest()))
        views.append(view)
    require(views[0] == views[1], 'evaluation_runtime_parity')
    normalized = json.dumps(views[0], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    result = dict(state='passed', revision='EVX-r1', evidence_kind='synthetic_mechanics',
        packet_sha256=sha256(packet_bytes).hexdigest(), runtimes=observations,
        normalized_sha256=sha256(normalized).hexdigest(), cleanup_verified=True,
        live_inference=False, held_out_opened=False)
    (output/'results.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared-postgres-bin', type=Path, required=True)
    parser.add_argument('--artifacts-dir', type=Path, required=True)
    parser.add_argument('--allow-local-processes', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        result = run(args.prepared_postgres_bin, args.artifacts_dir)
    except Exception:
        print(json.dumps({'state': 'failed', 'code': 'native_evaluation_failed'}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
