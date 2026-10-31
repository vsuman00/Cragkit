"""Parent control-flow and admission tests; native/provider boundaries are mocked."""
import asyncio
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_release_evaluation as parent
import evaluation_runtime
from cragkit.context import Cl100kCounter, count_context
from cragkit.contracts import parse_result


def digest(value):
    return sha256(value.encode()).hexdigest()


def prices():
    # Synthetic operator metadata exercises the gate; it is not a real price review.
    return dict(revision='ECR-price-r1', reviewed_on=datetime.now(timezone.utc).date().isoformat(),
        openai=dict(model='text-embedding-3-small', usd_per_million_input_tokens='0.02',
            source='https://developers.openai.com/api/docs/models/text-embedding-3-small'),
        cohere=dict(model='rerank-v5.0-fast', usd_per_million_input_tokens='0.02',
            source='https://cohere.com/blog/rerank-5'))


@pytest.fixture
def packet():
    text = 'Approved synthetic source.\n'
    query = dict(question_id='q', tenant_id='tenant', collection='docs', query='Approved source?', required_filters=[])
    doc = dict(tenant_id='tenant', collection='docs', document_id='doc', revision_id='r1', active=True,
               text=text, canonical_sha256=digest(text))
    labels = [{**query, 'answerability':'answerable', 'facets':[dict(facet_id='f', question='Label only?',
        state='supported', support=[dict(document_id='doc', revision_id='r1', start_byte=0,
            end_byte=len(text.encode()), text=text, canonical_sha256=digest(text))])]}]
    return dict(revision='EVX-r1', documents=[doc], queries=[query]), labels


def observation(packet, counter, runtime, kind):
    doc = packet['documents'][0]
    native, generation = digest('native-revision'), digest('generation')
    evidence = dict(evidence_id='evidence', collection='docs', document_id='doc', revision_id=native,
        chunk_id='chunk', source_locator='synthetic:parent', start_byte=0, end_byte=len(doc['text'].encode()),
        text=doc['text'], source_sha256=doc['canonical_sha256'], text_sha256=doc['canonical_sha256'])
    counted = count_context([evidence], max_tokens=20000, reserve=256, counter=counter, counting_mode='strict')
    rows = []
    for mode in parent.MODES:
        result = parse_result(dict(request_id=mode, status='partial', evidence=[evidence], context=counted['context'],
            usage=dict(attempt_count=1, provider_calls=0, context_counting='strict', context_tokens=counted['context_tokens'],
                cost_kind='known', cost_usd=0), versions=dict(tokenizer='cl100k_base'))).model_dump(mode='json')
        rows.append(dict(question_id='q', mode=mode, result=result, latency_ms=1))
    receipt = dict(tenant_id='tenant', collection='docs', document_id='doc', logical_revision_id='r1',
        revision_id=native, generation_id=generation, canonical_sha256=doc['canonical_sha256'],
        embedding_profile='fake_embedding_1536_v1' if kind == 'mechanics' else 'openai_te3small_1536_r1', active=True)
    return dict(revision='EVX-r1', runtime=runtime, kind=kind, receipts=[receipt], rows=rows, cleanup_verified=True)


@pytest.fixture
def flow(monkeypatch, packet):
    runtime_packet, labels = packet
    counter = Cl100kCounter.from_file(parent.ROOT/'artifacts/tokenizers/cl100k_base.tiktoken')
    class Flow(list):
        pass
    events = Flow()
    events.packet, events.counter = runtime_packet, counter
    class Bound:
        def runtime_packet(self):
            return deepcopy(runtime_packet)
        def provenance(self):
            return dict(split='development', packet_sha256='p', labels_sha256='l', seal_sha256='s',
                candidate_source_verified=False, source_commit=None, compiled_artifacts_verified=False, held_out_opened=False)
    def bind(*args, **kwargs):
        events.append(('bind', kwargs))
        return Bound()
    async def execute(packet, prepared, output, *, runtime, kind, send=None, tape=None, audits=None):
        assert 'facets' not in json.dumps(packet)
        events.append(('execute', runtime, kind, send is not None))
        if audits is not None:
            audits.append(dict(question_id='q', mode='reranked_hybrid', query_sha256=digest('Approved source?'),
                profile_id='fake_reranker_v1' if kind == 'mechanics' else 'cohere_v5fast_evaluation_v1',
                candidates=[dict(candidate_id='evidence', text_sha256=digest('Approved synthetic source.\n'))]))
        return observation(packet, counter, runtime, kind)
    monkeypatch.setattr(parent, 'bind_packet', bind)
    monkeypatch.setattr(parent, 'labels_for', lambda *args: deepcopy(labels))
    monkeypatch.setattr(parent, 'execute', execute)
    monkeypatch.setattr(evaluation_runtime, 'verify_runtime', lambda *args:dict(identity_sha256='identity'))
    return events


def test_mechanics_scores_all_modes_and_never_claims_live_quality(tmp_path, flow):
    result = asyncio.run(parent.run_comparison(prepared_postgres_bin=tmp_path, output=tmp_path/'run'))
    assert result['state'] == 'passed' and result['normalized_parity'] and result['metric_targets_passed']
    assert result['evidence_kind'] == 'synthetic_mechanics' and not result['live_quality_accepted']
    assert result['recorder'] is None and result['replay_http_calls'] == 0
    assert [row[1] for row in flow if row[0] == 'execute'] == ['python','node']
    scores = json.loads((tmp_path/'run/scores.json').read_text())
    assert all(report['row_count'] == 5 and report['question_count'] == 1 for report in scores.values())
    assert (tmp_path/'run/results.json').stat().st_mode & 0o777 == 0o600


def test_catastrophic_stage_failure_preserves_every_metric_denominator(tmp_path, flow, monkeypatch):
    async def fail(*args, **kwargs):
        raise RuntimeError('private failure must not enter output')
    monkeypatch.setattr(parent, 'execute', fail)
    result = asyncio.run(parent.run_comparison(prepared_postgres_bin=tmp_path, output=tmp_path/'run'))
    assert result['state'] == 'failed' and not result['normalized_parity']
    scores = json.loads((tmp_path/'run/scores.json').read_text())
    for report in scores.values():
        assert report['counts']['operational_failures'] == 5 and report['row_count'] == 5
        assert not report['ready']
    assert 'private failure' not in ''.join(p.read_text() for p in (tmp_path/'run').glob('*.json'))


@pytest.mark.parametrize('corruption', [
    'missing_mode', 'duplicate_mode', 'reordered_modes', 'missing_receipt',
    'wrong_logical_revision', 'extra_receipt_field',
])
def test_malformed_worker_matrix_becomes_complete_failure_denominators(
        tmp_path, flow, monkeypatch, corruption):
    original_execute = parent.execute

    async def malformed(*args, **kwargs):
        value = await original_execute(*args, **kwargs)
        if kwargs['runtime'] == 'python':
            if corruption == 'missing_mode':
                value['rows'].pop()
            elif corruption == 'duplicate_mode':
                value['rows'][-1] = deepcopy(value['rows'][0])
            elif corruption == 'reordered_modes':
                value['rows'].reverse()
            elif corruption == 'missing_receipt':
                value['receipts'].clear()
            elif corruption == 'wrong_logical_revision':
                value['receipts'][0]['logical_revision_id'] = 'unknown'
            else:
                value['receipts'][0]['unexpected'] = 'invalid'
        return value

    monkeypatch.setattr(parent, 'execute', malformed)
    result = asyncio.run(parent.run_comparison(
        prepared_postgres_bin=tmp_path, output=tmp_path/'run'))
    assert result['state'] == 'failed' and not result['live_quality_accepted']
    assert result['stages'] == {'python_mechanics':'failed', 'node_mechanics':'completed'}
    scores = json.loads((tmp_path/'run/scores.json').read_text())
    assert set(scores) == {'python_mechanics', 'node_mechanics'}
    failed = scores['python_mechanics']
    assert failed['row_count'] == 5 and failed['counts']['operational_failures'] == 5
    assert all(mode['aggregate']['total_questions'] == 1 for mode in failed['modes'].values())
    assert (tmp_path/'run/python_mechanics-raw.json').exists()
    normalized = json.loads((tmp_path/'run/python_mechanics.json').read_text())
    assert len(normalized['rows']) == 5 and not normalized['receipts']


def test_runtime_rejection_precedes_any_packet_binding(tmp_path, flow, monkeypatch):
    def fail(*args):
        raise RuntimeError('unverified runtime')
    monkeypatch.setattr(evaluation_runtime, 'verify_runtime', fail)
    with pytest.raises(RuntimeError):
        asyncio.run(parent.run_comparison(prepared_postgres_bin=tmp_path, output=tmp_path/'run',
            mode='live', runtime_receipt={}, keys=dict(openai='synthetic-openai', cohere='synthetic-cohere'),
            allow_provider_calls=True, admission_dir=tmp_path/'admission', price_review=prices()))
    assert not flow and not (tmp_path/'run').exists()


def test_mock_recordings_cannot_be_replayed_or_claim_live_quality(tmp_path, flow, monkeypatch):
    class MockRecorder:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def snapshot(self):
            return dict(evidence_kind='mock', failed=False, cleanup_verified=True,
                        budget=dict(attempts=0), journal=dict(sealed=True, attempts=0, completed=0))
    monkeypatch.setattr(parent, 'RecordedProviderSend', MockRecorder)
    monkeypatch.setattr(parent, 'load_recordings', lambda *args:pytest.fail('Mock tape adopted'))
    result = asyncio.run(parent.run_comparison(prepared_postgres_bin=tmp_path, output=tmp_path/'run',
        mode='live', runtime_receipt={}, keys=dict(openai='synthetic-openai', cohere='synthetic-cohere'),
        allow_provider_calls=True, admission_dir=tmp_path/'admission', price_review=prices()))
    assert not result['live_quality_accepted'] and result['state'] == 'failed'
    assert result['evidence_kind'] == 'unverified_provider_execution'
    assert result['stages']['node_replay'] == 'not_run_recordings_incomplete'
    assert len([e for e in flow if e[0] == 'execute']) == 1
    assert json.loads((tmp_path/'run/provider-accounting.json').read_text())['budget']['attempts'] == 0


def test_live_parent_control_flow_with_mocked_native_provider_boundaries(tmp_path, flow, monkeypatch):
    """A stubbed protocol test, never evidence of genuine inference or storage."""
    class Recorder:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def snapshot(self):
            return dict(evidence_kind='live', failed=False, cleanup_verified=True,
                        budget=dict(attempts=1), journal=dict(sealed=True, attempts=1, completed=1))
    class Replay:
        def __init__(self, tape):
            assert len(tape) == 1
        def assert_complete(self):
            pass
    monkeypatch.setattr(parent, 'RecordedProviderSend', Recorder)
    monkeypatch.setattr(parent, 'ReplaySend', Replay)
    monkeypatch.setattr(parent, 'load_recordings', lambda *args:('opaque unit-test record',))
    result = asyncio.run(parent.run_comparison(prepared_postgres_bin=tmp_path, output=tmp_path/'run',
        mode='live', runtime_receipt={}, keys=dict(openai='synthetic-openai', cohere='synthetic-cohere'),
        allow_provider_calls=True, admission_dir=tmp_path/'admission', price_review=prices()))
    assert result['state'] == 'passed' and result['normalized_parity']
    assert result['live_admission_attempts_this_run'] == 1
    assert result['live_http_calls_this_run'] == dict(lower_bound=1, upper_bound=1, exact=1)
    assert result['replay_http_calls'] == 0 and len(result['stages']) == 3
    assert len([row for row in flow if row[0] == 'execute']) == 3
    assert (tmp_path/'run/python_live.json').exists()


def test_recorder_cleanup_failure_still_saves_accounting_and_propagates_failure(tmp_path, flow, monkeypatch):
    class ClosingRecorder:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            raise RuntimeError('private close failure')
        def snapshot(self):
            return dict(evidence_kind='live', failed=True, cleanup_verified=False,
                        budget=dict(attempts=1), journal=dict(sealed=False, attempts=1, completed=0))
    monkeypatch.setattr(parent, 'RecordedProviderSend', ClosingRecorder)
    with pytest.raises(RuntimeError):
        asyncio.run(parent.run_comparison(prepared_postgres_bin=tmp_path, output=tmp_path/'run',
            mode='live', runtime_receipt={}, keys=dict(openai='synthetic-openai', cohere='synthetic-cohere'),
            allow_provider_calls=True, admission_dir=tmp_path/'admission', price_review=prices()))
    assert json.loads((tmp_path/'run/provider-accounting.json').read_text())['budget']['attempts'] == 1
    failure = json.loads((tmp_path/'run/failure.json').read_text())
    assert failure['state'] == 'failed' and not failure['cleanup_verified']
    scores = json.loads((tmp_path/'run/scores.json').read_text())
    assert len(scores) == 3 and all(value['row_count'] == 5 for value in scores.values())


def test_caller_cancellation_survives_and_does_not_start_next_runtime(tmp_path, flow, monkeypatch):
    async def cancel(*args, **kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(parent, 'execute', cancel)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(parent.run_comparison(prepared_postgres_bin=tmp_path, output=tmp_path/'run'))
    assert not any(event[0] == 'execute' for event in flow)
    assert json.loads((tmp_path/'run/failure.json').read_text())['state'] == 'failed'


def test_accounting_write_fault_cannot_replace_caller_cancellation(tmp_path, flow, monkeypatch):
    class CancelledRecorder:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            raise asyncio.CancelledError()
        def snapshot(self):
            return dict(evidence_kind='live', failed=True, cleanup_verified=False,
                        budget=dict(attempts=1), journal=dict(sealed=False, attempts=1, completed=0))
    monkeypatch.setattr(parent, 'RecordedProviderSend', CancelledRecorder)
    original_save = parent.save
    def fail_accounting(path, value):
        if path.name == 'provider-accounting.json':
            raise OSError('private disk failure')
        return original_save(path, value)
    monkeypatch.setattr(parent, 'save', fail_accounting)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(parent.run_comparison(prepared_postgres_bin=tmp_path, output=tmp_path/'run',
            mode='live', runtime_receipt={}, keys=dict(openai='synthetic-openai', cohere='synthetic-cohere'),
            allow_provider_calls=True, admission_dir=tmp_path/'admission', price_review=prices()))
    assert len(json.loads((tmp_path/'run/scores.json').read_text())) == 3


@pytest.mark.parametrize('unused_tape', [False, True])
def test_replay_retains_healthy_primary_and_preserves_unused_tape_failures(tmp_path, flow, monkeypatch, unused_tape):
    previous = tmp_path/'prior';previous.mkdir(mode=0o700)
    tape = previous/'recordings';tape.mkdir(mode=0o700)
    provenance = parent.bind_packet().provenance()
    parent.save(previous/'run-binding.json', dict(mode='live', packet=provenance, runtime_identity_sha256='identity'))
    parent.save(previous/'provider-accounting.json', dict(evidence_kind='live', failed=False, cleanup_verified=True,
        budget=dict(attempts=1), journal=dict(sealed=True, attempts=1, completed=1)))
    parent.save(previous/'python_live.json', observation(flow.packet, flow.counter, 'python', 'provider'))
    monkeypatch.setattr(parent, 'load_recordings', lambda *args:('synthetic opaque tape record',))
    class Replay:
        def __init__(self, rows):
            assert len(rows) == 1
        def assert_complete(self):
            if unused_tape:
                raise ValueError('unused recorded call')
    monkeypatch.setattr(parent, 'ReplaySend', Replay)
    result = asyncio.run(parent.run_comparison(prepared_postgres_bin=tmp_path, output=tmp_path/'run',
        mode='replay', runtime_receipt={}, recordings=tape))
    assert result['stages']['python_live'] == 'retained_completed'
    assert result['recorder_accounting_origin'] == 'retained_live'
    assert result['live_admission_attempts_this_run'] == 0
    assert result['live_http_calls_this_run']['exact'] == 0
    assert all(event[1] in ('python','node') for event in flow if event[0] == 'execute')
    assert not any(event[0] == 'execute' and event[2] == 'mechanics' for event in flow)
    scores = json.loads((tmp_path/'run/scores.json').read_text())
    assert len(scores) == 3 and all(value['row_count'] == 5 for value in scores.values())
    assert (result['state'] == 'failed') == unused_tape
    if unused_tape:
        assert result['stages']['python_replay'] == 'failed_replay_consumption'


def test_recording_count_mismatch_rejected_before_replay_execution(tmp_path, flow, monkeypatch):
    previous=tmp_path/'prior';previous.mkdir(mode=0o700)
    tape=previous/'recordings';tape.mkdir(mode=0o700)
    parent.save(previous/'run-binding.json', dict(mode='live', packet=parent.bind_packet().provenance(),
        runtime_identity_sha256='identity'))
    parent.save(previous/'provider-accounting.json', dict(evidence_kind='live', failed=False, cleanup_verified=True,
        budget=dict(attempts=2), journal=dict(sealed=True, attempts=2, completed=2)))
    parent.save(previous/'python_live.json', observation(flow.packet, flow.counter, 'python', 'provider'))
    monkeypatch.setattr(parent, 'load_recordings', lambda *args:('only-one',))
    with pytest.raises(parent.ReleaseEvaluationError, match='recording_count'):
        asyncio.run(parent.run_comparison(prepared_postgres_bin=tmp_path, output=tmp_path/'run',
            mode='replay', runtime_receipt={}, recordings=tape))
    assert not any(event[0] == 'execute' for event in flow)
    assert len(json.loads((tmp_path/'run/scores.json').read_text())) == 3


@pytest.mark.parametrize('options', [dict(mode='live'), dict(keys={'openai':'unused'}),
    dict(mode='replay'), dict(mode='mechanics', allow_provider_calls=True)])
def test_invalid_execution_policy_rejects_before_binding(tmp_path, flow, options):
    with pytest.raises(parent.ReleaseEvaluationError):
        asyncio.run(parent.run_comparison(prepared_postgres_bin=tmp_path, output=tmp_path/'run', **options))
    assert not flow


def test_durable_admission_blocks_new_output_and_never_overwrites_prior_record(tmp_path):
    directory = tmp_path/'admission'
    config = dict(frozen='candidate')
    parent.admit_once(directory, config, tmp_path/'first')
    record = next(directory.iterdir());before=record.read_bytes()
    with pytest.raises(FileExistsError):
        parent.admit_once(directory, config, tmp_path/'second')
    assert record.read_bytes() == before and record.stat().st_mode & 0o777 == 0o600


def test_private_keys_are_explicit_owner_only_files_and_never_shell_evaluated(tmp_path):
    path = tmp_path/'private.env'
    path.write_text('UNRELATED=value\nOPENAI_API_KEY="synthetic-$(literal)"\n');path.chmod(0o600)
    assert parent.private_key(path, env_name='OPENAI_API_KEY') == 'synthetic-$(literal)'
    path.chmod(0o644)
    with pytest.raises(parent.ReleaseEvaluationError):
        parent.private_key(path, env_name='OPENAI_API_KEY')
    path.chmod(0o600)
    link=tmp_path/'link';link.symlink_to(path)
    with pytest.raises(parent.ReleaseEvaluationError) as error:
        parent.private_key(link)
    assert error.value.__context__ is None


def test_unexpected_cli_key_paths_are_not_read_in_offline_modes(tmp_path, monkeypatch):
    monkeypatch.setattr(parent, 'private_key', lambda *args, **kwargs:pytest.fail('Credential file read'))
    assert parent.main(['--prepared-postgres-bin', str(tmp_path), '--output', str(tmp_path/'run'),
        '--allow-local-processes', '--openai-env-file', str(tmp_path/'private')]) == 1
