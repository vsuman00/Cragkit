"""Explicit disposable evaluation: fake mechanics, one live run, or sealed replay."""
from __future__ import annotations

import argparse
import asyncio
import base64
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys
import time

from check_native_evaluation import _node
from cragkit.context import Cl100kCounter, count_context
from cragkit.contracts import parse_result
from cragkit.embeddings import FAKE_PROFILE, OPENAI_PROFILE
from evaluation_packet import bind_packet, _read, _json
from evaluation_payloads import EvaluationPayloadGate
from postgres_vector_fixture import V6PostgresFixture
from provider_adapters import ReplaySend
from provider_http import HttpProviderSend
from provider_journal import load_recordings
from recorded_provider import RecordedProviderSend
from retrieval_evaluation import MODES, query_variants, run_evaluation

ROOT = Path(__file__).resolve().parents[1]


class ReleaseEvaluationError(ValueError):
    """Never include credentials, connection strings or source/query text."""


def require(condition, code):
    if not condition:
        raise ReleaseEvaluationError(code)


def save(path, value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode()+b'\n'
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def failed_observation(packet, runtime, kind):
    return dict(revision='EVX-r1', runtime=runtime, kind=kind, receipts=[], cleanup_verified=False,
        rows=[dict(question_id=q['question_id'], mode=mode, latency_ms=0,
                   result=dict(operational_failure=True, error_code='evaluation_stage_failed'))
              for q in packet['queries'] for mode in MODES])


def normalized(observation):
    rows = deepcopy(observation['rows'])
    for row in rows:
        row.pop('latency_ms')
        for stage in row['result'].get('usage', {}).get('stage_durations', []):
            stage['duration_ms'] = 0
    return dict(receipts=observation['receipts'], rows=rows)


def check_observation(packet, observation, *, profile, counter):
    from evaluation_scoring import validate_observation

    # Validate the full matrix and revision aliases before accepting a stage.
    # This uses only runtime input; reviewed labels remain outside execution.
    validate_observation(packet, observation)
    require(observation.get('cleanup_verified') is True, 'evaluation_cleanup_unverified')
    for receipt in observation['receipts']:
        require(receipt['embedding_profile'] == profile.profile_id, 'evaluation_profile_identity')
    for row in observation['rows']:
        if row['result'].get('operational_failure'):
            continue
        result = parse_result(row['result'])
        require(result.versions.policy == 'unassessed.v0' and result.status != 'sufficient'
            and result.execution == 'complete' and all(f.state == 'unknown' for f in result.facets),
            'evaluation_label_policy')
        counted = count_context([e.model_dump(mode='json') for e in result.evidence],
            max_tokens=20000, reserve=256, counter=counter, counting_mode='strict')
        require(result.context == counted['context'] and result.usage.context_counting == 'strict'
            and result.usage.context_tokens == counted['context_tokens']
            and result.usage.provider_calls <= 8 and result.usage.attempt_count <= 3,
            'evaluation_result_accounting')


def labels_for(root, bound):
    provenance = bound.provenance()
    name = 'evaluation/questions/'+('dev.json' if provenance['split'] == 'development' else 'held_out.json')
    labels = _json(_read(root, name, 262144, provenance['labels_sha256']))
    require(labels.get('human_review', {}).get('state') == 'approved', 'evaluation_labels_unapproved')
    return labels['questions']


def gate_for(packet):
    queries = []
    for query in packet['queries']:
        queries.append(query['query'])
        queries.extend(variant['query'] for variant in query_variants(query['query']))
    return EvaluationPayloadGate([d['text'] for d in packet['documents']], queries)


def admit_once(directory, configuration, output):
    """One durable admission per frozen candidate/held-out packet; never auto-remove."""
    directory = Path(directory)
    if not directory.exists():
        directory.mkdir(mode=0o700)
    parent = os.open(directory.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    info = directory.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o700, 'evaluation_admission_directory')
    identity = sha256(json.dumps(configuration, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    path = directory/(identity+'.json')
    save(path, dict(revision='ECR-r1', state='admitted_once', configuration_sha256=identity,
        output=str(output), started_unix=int(time.time())))
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


async def execute(packet, prepared_bin, output, *, runtime, kind, send=None, tape=None, audits=None):
    with V6PostgresFixture(prepared_bin, output) as fixture:
        roles = await fixture.provision(
            tenants=tuple(sorted({d['tenant_id'] for d in packet['documents']})),
            collections=tuple(sorted({d['collection'] for d in packet['documents']})),
            enable_openai_profile=kind != 'mechanics')
        options = dict(reader_config=roles.reader, writer_config=roles.writer,
            tokenizer_path=str(ROOT/'artifacts/tokenizers/cl100k_base.tiktoken'), kind=kind)
        async with asyncio.timeout(930):
            if runtime == 'node':
                if tape is not None:
                    options['recordings'] = [dict(provider=r.provider, model=r.model, replay_key=r.replay_key,
                        response_base64=base64.b64encode(r.response).decode()) for r in tape]
                observation = await _node(packet, options)
            else:
                observation = await run_evaluation(packet, **options, send=send,
                    on_rerank_input=None if audits is None else audits.append)
    # Fixture close is part of a stage. A failure here is not successful runtime cleanup.
    require(observation.get('cleanup_verified') is True, 'evaluation_cleanup_unverified')
    return observation


async def run_comparison(*, prepared_postgres_bin, output, mode='mechanics', runtime_receipt=None,
                         keys=None, allow_provider_calls=False, admission_dir=None, recordings=None,
                         price_review=None):
    from evaluation_scoring import score_observation
    from evaluation_runtime import verify_runtime

    require(type(mode) is str and mode in ('mechanics', 'live', 'replay'), 'evaluation_mode')
    output = Path(output).absolute()
    require(not output.exists(), 'evaluation_fresh_output_required')
    if mode == 'live':
        require(allow_provider_calls is True and type(keys) is dict and set(keys) == {'openai', 'cohere'}
            and admission_dir is not None and recordings is None, 'evaluation_live_not_enabled')
        HttpProviderSend(keys)  # Validate explicit credentials without opening an HTTP client.
        from evaluation_pricing import validate_price_review
        price_review = validate_price_review(price_review)
    else:
        require(keys is None and allow_provider_calls is False and admission_dir is None,
                'evaluation_unexpected_credentials')
        require(price_review is None, 'evaluation_unexpected_price_review')
        require((mode == 'replay') == (recordings is not None), 'evaluation_recordings_required')
    require(mode == 'mechanics' or runtime_receipt is not None, 'evaluation_runtime_identity_required')
    identity = verify_runtime(ROOT, runtime_receipt) if runtime_receipt is not None else None
    bound = bind_packet(ROOT, split='development' if mode == 'mechanics' else 'held_out',
        allow_held_out=mode != 'mechanics', require_candidate=mode != 'mechanics')
    packet = bound.runtime_packet()
    counter = Cl100kCounter.from_file(ROOT/'artifacts/tokenizers/cl100k_base.tiktoken')
    configuration = _json(_read(ROOT, 'evaluation/release/V6-candidate.json', 65536))
    output.mkdir(parents=True, mode=0o700)
    provenance = bound.provenance()
    save(output/'run-binding.json', dict(revision='ECR-r1', mode=mode, packet=provenance,
        runtime_identity_sha256=None if identity is None else identity['identity_sha256']))
    if price_review is not None:
        save(output/'price-review.json', price_review)
    observations, audits, stages, recorder_snapshot = {}, [], {}, None

    def recheck():
        if identity is not None:
            verified = verify_runtime(ROOT, runtime_receipt)
            require(verified['identity_sha256'] == identity['identity_sha256'], 'evaluation_runtime_drift')

    async def stage(name, *, runtime, kind, send=None, tape=None, collect=False):
        try:
            recheck()
            value = await execute(packet, prepared_postgres_bin, output/name,
                runtime=runtime, kind=kind, send=send, tape=tape, audits=audits if collect else None)
            save(output/(name+'-raw.json'), value)
            require(value.get('runtime') == runtime and value.get('kind') == kind
                and value.get('revision') == 'EVX-r1', 'evaluation_result_identity')
            recheck()
            check_observation(packet, value, profile=FAKE_PROFILE if mode == 'mechanics' else OPENAI_PROFILE,
                              counter=counter)
            stages[name] = 'completed'
        except asyncio.CancelledError:
            raise
        except Exception:
            value = failed_observation(packet, runtime, kind)
            stages[name] = 'failed'
        observations[name] = value
        return value

    expected = [('python_mechanics', 'python', 'mechanics'), ('node_mechanics', 'node', 'mechanics')]
    if mode != 'mechanics':
        expected = [('python_live', 'python', 'provider'), ('python_replay', 'python', 'provider'),
                    ('node_replay', 'node', 'replay')]

    def finish_rows(reason='not_run_recordings_incomplete'):
        for name, runtime, kind in expected:
            if name not in observations:
                observations[name] = failed_observation(packet, runtime, kind)
                stages[name] = reason
        for name, value in observations.items():
            path = output/(name+'.json')
            if not path.exists():
                save(path, value)
        if not (output/'rerank-inputs.json').exists():
            save(output/'rerank-inputs.json', audits)
        reviewed = labels_for(ROOT, bound)
        scores = {name:score_observation(packet, reviewed, value, rerank_inputs=audits)
                  for name, value in observations.items()}
        if not (output/'scores.json').exists():
            save(output/'scores.json', scores)
        return scores

    def http_counts():
        if mode != 'live':
            return dict(lower_bound=0, upper_bound=0, exact=0)
        admitted = recorder_snapshot['budget']['attempts']
        completed = recorder_snapshot['journal']['completed']
        return dict(lower_bound=completed, upper_bound=admitted,
                    exact=admitted if admitted == completed else None)

    tape = None
    try:
        if mode == 'mechanics':
            await stage('python_mechanics', runtime='python', kind='mechanics', collect=True)
            await stage('node_mechanics', runtime='node', kind='mechanics')
        elif mode == 'live':
            recheck()
            admit_once(admission_dir, configuration, output)
            recorder = RecordedProviderSend(keys, gate_for(packet), output/'recordings', counter=counter, enabled=True)
            live_failure = None
            try:
                async with recorder:
                    await stage('python_live', runtime='python', kind='provider', send=recorder, collect=True)
            except BaseException as error:
                live_failure = error
            try:
                recorder_snapshot = recorder.snapshot()
                save(output/'provider-accounting.json', recorder_snapshot)
            except BaseException as error:
                if live_failure is None:
                    live_failure = error
            if live_failure is not None:
                raise live_failure
            if (recorder_snapshot['evidence_kind'] == 'live' and not recorder_snapshot['failed'] and recorder_snapshot['cleanup_verified']
                    and recorder_snapshot['journal']['sealed'] and stages['python_live'] == 'completed'):
                tape = load_recordings(output/'recordings')
                require(len(tape) == recorder_snapshot['budget']['attempts']
                    == recorder_snapshot['journal']['attempts'] == recorder_snapshot['journal']['completed'],
                    'evaluation_recording_count')
                save(output/'python_live.json', observations['python_live'])
        else:
            tape_path = Path(recordings).absolute()
            previous = _json(_read(tape_path.parent, 'run-binding.json', 65536))
            require(previous.get('mode') == 'live' and previous.get('packet') == provenance
                and previous.get('runtime_identity_sha256') == identity['identity_sha256'],
                'evaluation_recording_provenance')
            recorder_snapshot = _json(_read(tape_path.parent, 'provider-accounting.json', 1048576))
            require(recorder_snapshot.get('evidence_kind') == 'live'
                and recorder_snapshot.get('failed') is False and recorder_snapshot.get('cleanup_verified') is True
                and recorder_snapshot.get('journal', {}).get('sealed') is True
                and type(recorder_snapshot.get('budget', {}).get('attempts')) is int
                and 0 < recorder_snapshot['budget']['attempts'] <= 60, 'evaluation_recording_health')
            original_live = _json(_read(tape_path.parent, 'python_live.json', 16*1024*1024))
            require(original_live.get('runtime') == 'python' and original_live.get('kind') == 'provider',
                    'evaluation_recording_provenance')
            check_observation(packet, original_live, profile=OPENAI_PROFILE, counter=counter)
            observations['python_live'] = original_live
            stages['python_live'] = 'retained_completed'
            save(output/'python_live.json', original_live)
            tape = load_recordings(tape_path)
            require(len(tape) == recorder_snapshot['budget']['attempts']
                == recorder_snapshot['journal']['attempts'] == recorder_snapshot['journal']['completed'],
                'evaluation_recording_count')
        if tape is not None:
            require(bool(tape), 'evaluation_empty_recordings')
            replay = ReplaySend(tape)
            python = await stage('python_replay', runtime='python', kind='provider', send=replay,
                                 collect=mode == 'replay')
            if not any(r['result'].get('operational_failure') for r in python['rows']):
                try:
                    replay.assert_complete()
                except Exception:
                    observations['python_replay'] = failed_observation(packet, 'python', 'provider')
                    stages['python_replay'] = 'failed_replay_consumption'
            await stage('node_replay', runtime='node', kind='replay', tape=tape)
        # Reviewed labels are loaded for scoring only after native execution ends.
        scores = finish_rows()
        accepted_stages = ('completed', 'retained_completed')
        views = [normalized(o) for name, o in observations.items() if stages[name] in accepted_stages]
        parity = bool(views) and all(view == views[0] for view in views[1:]) and all(
            state in accepted_stages for state in stages.values())
        targets = all(report['ready'] for report in scores.values())
        recheck()
        result = dict(revision='ECR-r1', state='passed' if parity and targets else 'failed',
            evidence_kind='synthetic_mechanics' if mode == 'mechanics' else
                'unverified_provider_execution' if recorder_snapshot is not None
                and recorder_snapshot['evidence_kind'] != 'live' else 'live_and_recorded_replay',
            live_quality_accepted=mode != 'mechanics' and parity and targets,
            packet=provenance, runtime_identity_sha256=None if identity is None else identity['identity_sha256'],
            stages=stages, normalized_parity=parity, metric_targets_passed=targets,
            recorder=recorder_snapshot, replay_http_calls=0,
            live_admission_attempts_this_run=recorder_snapshot['budget']['attempts'] if mode == 'live' else 0,
            live_http_calls_this_run=http_counts(),
            recorder_accounting_origin='current_live' if mode == 'live' else 'retained_live' if mode == 'replay' else 'none',
            cleanup_verified=all(o['cleanup_verified'] for o in observations.values()))
        save(output/'results.json', result)
        return result
    except BaseException:
        try:
            finish_rows('not_run_parent_failed')
        except Exception:
            pass
        try:
            save(output/'failure.json', dict(revision='ECR-r1', state='failed', code='release_evaluation_failed',
                held_out_opened=provenance['held_out_opened'], cleanup_verified=False))
        except OSError:
            pass
        raise


def private_key(path, *, env_name=None):
    """Read one explicitly selected owner-only file; never discover credentials."""
    path = Path(path).absolute()
    failed = False
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1 and info.st_size <= 16384,
                'evaluation_private_key_file')
            raw = stream.read(16385)
        require(len(raw) <= 16384, 'evaluation_private_key_file')
        text = raw.decode('utf-8')
        if env_name is None:
            value = text.strip()
        else:
            values = [line.split('=', 1)[1].strip() for line in text.splitlines()
                      if line.startswith(env_name+'=')]
            require(len(values) == 1, 'evaluation_private_key_file')
            value = values[0]
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
        require(1 <= len(value) <= 4096 and all(33 <= ord(c) <= 126 for c in value),
                'evaluation_private_key_file')
    except ReleaseEvaluationError:
        raise
    except (OSError, UnicodeError, ValueError):
        failed = True
    if failed:
        raise ReleaseEvaluationError('evaluation_private_key_file')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('mechanics', 'live', 'replay'), default='mechanics')
    parser.add_argument('--prepared-postgres-bin', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runtime-receipt', type=Path)
    parser.add_argument('--recordings', type=Path)
    parser.add_argument('--allow-provider-calls', action='store_true')
    parser.add_argument('--admission-dir', type=Path)
    parser.add_argument('--openai-env-file', type=Path)
    parser.add_argument('--cohere-key-file', type=Path)
    parser.add_argument('--price-review', type=Path)
    parser.add_argument('--allow-local-processes', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        keys = None
        price_review = None
        if args.mode == 'live':
            require(args.allow_provider_calls and args.openai_env_file is not None
                and args.cohere_key_file is not None and args.admission_dir is not None and args.price_review is not None,
                'evaluation_live_not_enabled')
            from evaluation_pricing import load_price_review
            price_review = load_price_review(args.price_review)
            keys = dict(openai=private_key(args.openai_env_file, env_name='OPENAI_API_KEY'),
                        cohere=private_key(args.cohere_key_file))
        else:
            require(args.openai_env_file is None and args.cohere_key_file is None and args.price_review is None,
                    'evaluation_unexpected_credentials')
        result = asyncio.run(run_comparison(prepared_postgres_bin=args.prepared_postgres_bin,
            output=args.output, mode=args.mode, runtime_receipt=args.runtime_receipt, recordings=args.recordings,
            keys=keys, allow_provider_calls=args.allow_provider_calls, admission_dir=args.admission_dir,
            price_review=price_review))
    except Exception:
        print(json.dumps({'state':'failed','code':'release_evaluation_failed'}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result['state'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
