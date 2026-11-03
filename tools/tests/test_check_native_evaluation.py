"""Reject misleading native acceptance evidence; no database or provider work."""
import asyncio
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_native_evaluation as checker
from cragkit.context import Cl100kCounter, count_context
from cragkit.contracts import parse_result
from cragkit.embeddings import FAKE_PROFILE


@pytest.fixture(scope='module')
def counter():
    return Cl100kCounter.from_file(checker.ROOT/'artifacts/tokenizers/cl100k_base.tiktoken')


def sample(counter):
    packet = json.loads(checker.PACKET.read_text())
    documents = sorted(packet['documents'], key=lambda d: (
        *(part.encode() for part in checker._identity(d)), d['active'], d['revision_id'].encode()))
    receipts = [dict(tenant_id=d['tenant_id'], collection=d['collection'], document_id=d['document_id'],
        logical_revision_id=d['revision_id'], revision_id='native-'+d['canonical_sha256'],
        generation_id='generation-'+d['canonical_sha256'], canonical_sha256=d['canonical_sha256'],
        embedding_profile=FAKE_PROFILE.profile_id, active=d['active']) for d in documents]
    rows = []
    for query in packet['queries']:
        selected = next((d for d in documents if d['active'] and d['tenant_id'] == query['tenant_id']
            and d['collection'] == query['collection']
            and all(checker._matches(f, d) for f in query['required_filters'])), None)
        evidence = []
        if selected is not None and query['question_id'] not in ('foreign', 'missing', 'historical'):
            raw = selected['text'].encode()
            evidence = [dict(evidence_id='evidence', collection=selected['collection'],
                document_id=selected['document_id'], revision_id='native-'+selected['canonical_sha256'],
                chunk_id='chunk', source_locator='fixture:synthetic', start_byte=0, end_byte=len(raw),
                text=selected['text'], source_sha256=sha256(raw).hexdigest(), text_sha256=sha256(raw).hexdigest())]
        for mode in checker.MODES:
            selected_evidence = [] if query['question_id'] == 'cache' and mode == 'lexical' else evidence
            counted = count_context(selected_evidence, max_tokens=20000, counter=counter, counting_mode='strict')
            result = parse_result(dict(request_id='row-'+query['question_id']+'-'+mode,
                status='partial' if selected_evidence else 'insufficient', evidence=selected_evidence,
                context=counted['context'], usage=dict(attempt_count=1, provider_calls=0,
                    cost_kind='known', cost_usd=0, context_tokens=counted['context_tokens'],
                    context_counting='strict'), versions=dict(tokenizer='cl100k_base'))).model_dump(mode='json')
            rows.append(dict(question_id=query['question_id'], mode=mode, result=result, latency_ms=1.5))
    return packet, dict(revision='EVX-r1', runtime='python', kind='mechanics', receipts=receipts,
                        rows=rows, cleanup_verified=True)


def test_comparison_preserves_wire_but_normalizes_only_timing(counter):
    packet, value = sample(counter)
    value['rows'][0]['result']['usage']['stage_durations'] = [dict(stage='search', duration_ms=3)]
    original = deepcopy(value)
    view = checker.validate_observation(packet, value, 'python', counter=counter)
    assert view['rows'][0]['result']['usage']['stage_durations'][0]['duration_ms'] == 0
    assert value == original and 'latency_ms' not in view['rows'][0]
    altered = deepcopy(value)
    altered['rows'][0]['result']['request_id'] = 'different-request'
    assert checker.validate_observation(packet, altered, 'python', counter=counter) != view


@pytest.mark.parametrize('mutation,code', [
    ('missing_row', 'row_count'), ('reordered_row', 'row_order'),
    ('operation', 'operational_failure'), ('cleanup', 'result_identity'),
    ('live_kind', 'result_identity'), ('receipt_source', 'receipt_identity'),
    ('cost', 'fake_cost'), ('token_lie', 'context_accounting'), ('context_lie', 'context_accounting'),
    ('source_lie', 'source_fidelity'), ('foreign', 'source_scope'),
    ('empty_positive', 'positive_missing'), ('latency', 'latency'),
])
def test_invalid_observation_never_claims_acceptance(counter, mutation, code):
    packet, value = sample(counter)
    first = value['rows'][0]
    if mutation == 'missing_row':
        value['rows'].pop()
    elif mutation == 'reordered_row':
        value['rows'][0], value['rows'][1] = value['rows'][1], value['rows'][0]
    elif mutation == 'operation':
        first['result'] = dict(operational_failure=True, error_code='provider_unavailable')
    elif mutation == 'cleanup':
        value['cleanup_verified'] = False
    elif mutation == 'live_kind':
        value['kind'] = 'provider'
    elif mutation == 'receipt_source':
        value['receipts'][0]['canonical_sha256'] = '0'*64
    elif mutation == 'cost':
        first['result']['usage'].update(cost_kind='unknown', cost_usd=None)
    elif mutation == 'token_lie':
        first['result']['usage']['context_tokens'] = 0
    elif mutation == 'context_lie':
        first['result']['context'] = 'invented context'
    elif mutation == 'source_lie':
        first['result']['evidence'][0]['source_sha256'] = '0'*64
    elif mutation == 'foreign':
        evidence = first['result']['evidence'][0]
        evidence['document_id'] = 'foreign-only'
        evidence['revision_id'] = 'native-'+packet['documents'][-1]['canonical_sha256']
    elif mutation == 'empty_positive':
        first['result'].update(status='insufficient', evidence=[])
    elif mutation == 'latency':
        first['latency_ms'] = float('nan')
    if mutation in ('source_lie', 'foreign', 'empty_positive'):
        counted = count_context(first['result']['evidence'], max_tokens=20000, counter=counter, counting_mode='strict')
        first['result']['context'] = counted['context']
        first['result']['usage']['context_tokens'] = counted['context_tokens']
    with pytest.raises(checker.NativeEvaluationError, match='^evaluation_'+code+'$'):
        checker.validate_observation(packet, value, 'python', counter=counter)


def test_nested_revision_filter_negation_preserves_requested_set():
    doc = dict(document_id='retry-policy', revision_id='r2')
    value = dict(op='and', filters=[dict(op='eq', field='document_id', value='retry-policy'),
        dict(op='not', filter=dict(op='in', field='revision_id', values=['r1']))])
    assert checker._matches(value, doc)
    doc['revision_id'] = 'r1'
    assert not checker._matches(value, doc)
    with pytest.raises(checker.NativeEvaluationError):
        checker._matches(dict(op='eq', field='tag', value='unknown'), doc)


def test_existing_output_is_preserved_before_native_setup(tmp_path, monkeypatch):
    marker = tmp_path/'owned';marker.write_text('preserve')
    monkeypatch.setattr(checker, 'V6PostgresFixture', lambda *a: pytest.fail('Native setup started'))
    with pytest.raises(checker.NativeEvaluationError, match='fresh_output'):
        checker.run(tmp_path/'not-prepared', tmp_path)
    assert marker.read_text() == 'preserve'


def test_node_replay_child_receives_only_explicit_safe_environment(monkeypatch):
    safe = dict(PATH='/synthetic/bin', LANG='C', LC_ALL='C', LC_CTYPE='C',
        TMPDIR='/synthetic/tmp', TZ='UTC')
    ambient = dict(safe, OPENAI_API_KEY='synthetic-only', COHERE_API_KEY='synthetic-only',
        APPLICATION_AUTH_TOKEN='synthetic-only', https_proxy='https://synthetic.invalid',
        all_proxy='https://synthetic.invalid', SSL_CERT_FILE='/synthetic/untrusted-ca',
        npm_config_registry='https://synthetic.invalid', NODE_OPTIONS='synthetic-options',
        PG_CUSTOM_PASSWORD='synthetic-only')
    monkeypatch.setattr(checker.os, 'environ', ambient)
    monkeypatch.setattr(checker.shutil, 'which', lambda name: '/synthetic/bin/node')
    captured = {}
    response = {'synthetic_child': True}

    class Input:
        def write(self, value):
            captured['stdin'] = value

        async def drain(self):
            pass

        def close(self):
            captured['stdin_closed'] = True

    class Process:
        returncode = None

        def __init__(self):
            self.stdin = Input()
            self.stdout = asyncio.StreamReader()
            self.stderr = asyncio.StreamReader()
            self.stdout.feed_data(json.dumps(response).encode())
            self.stdout.feed_eof()
            self.stderr.feed_eof()

        async def wait(self):
            self.returncode = 0
            return 0

    async def spawn(*arguments, **options):
        captured['arguments'] = arguments
        captured['environment'] = options['env']
        return Process()

    monkeypatch.setattr(checker.asyncio, 'create_subprocess_exec', spawn)
    packet = json.loads(checker.PACKET.read_text())
    options = {'kind': 'mechanics', 'tokenizer_path': '/synthetic/pinned-tokenizer'}
    assert asyncio.run(checker._node(packet, options)) == response
    assert captured['environment'] == safe
    assert captured['arguments'][0] == '/synthetic/bin/node'
    assert captured['stdin_closed'] is True
    assert json.loads(captured['stdin']) == {'packet': packet, 'options': options}
