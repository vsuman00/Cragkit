"""Small offline bridge boundary cases; no original artifacts or native services."""
import asyncio
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import time
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_recorded_compatibility as bridge
from provider_adapters import ProviderAdapterError, ProviderRequest, ReplaySend
from provider_journal import EvaluationJournal


def test_source_rejects_dirty_tracked_and_untracked_code(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(tmp_path), *args], stderr=subprocess.DEVNULL).decode().strip()
    git('init', '-q')
    path = tmp_path/'packages/python/source.py'
    path.parent.mkdir(parents=True)
    path.write_text('original')
    git('add', 'packages')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
    monkeypatch.setattr(bridge, 'SOURCE', git('rev-parse', 'HEAD'))
    monkeypatch.setattr(bridge, 'TREE', git('rev-parse', 'HEAD:packages'))
    bridge.source(tmp_path)
    path.write_text('changed')
    with pytest.raises(ValueError):
        bridge.source(tmp_path)
    path.write_text('original')
    (path.parent/'extra.py').write_text('untracked')
    with pytest.raises(ValueError):
        bridge.source(tmp_path)


def test_baseline_rejects_another_runtime_even_if_source_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, 'command', lambda *args, **kwargs: bridge.encoded(dict(
        identity='0'*64, source=bridge.BASE_SOURCE, packet={}, provenance={})))
    with pytest.raises(ValueError):
        bridge.baseline(tmp_path, tmp_path/'runtime.json')


@pytest.fixture
def products(tmp_path, monkeypatch):
    archive = tmp_path/'hosted.zip'
    with zipfile.ZipFile(archive, 'w') as hosted:
        for name in (bridge.WHEEL, bridge.NPM):
            hosted.writestr(name, name.encode())
            path = tmp_path/name
            path.parent.mkdir(parents=True)
            path.write_bytes(name.encode())
    digest = sha256(archive.read_bytes()).hexdigest()
    monkeypatch.setattr(bridge, 'CI_ARCHIVE', digest)
    metadata = dict(revision='CIB-r1', state='passed', source_commit=bridge.SOURCE,
        archive_sha256=digest, products=[dict(path=name, bytes=len(name.encode()),
            sha256=sha256(name.encode()).hexdigest()) for name in (bridge.WHEEL, bridge.NPM)])
    return tmp_path, archive, metadata


@pytest.mark.parametrize('tamper', ['product_and_metadata', 'archive', 'identity'])
def test_ci_products_cannot_be_rebound_with_a_forged_manifest(products, tamper):
    root, archive, metadata = products
    assert len(bridge.product_paths(root, metadata, archive)) == 2
    if tamper == 'product_and_metadata':
        (root/bridge.WHEEL).write_bytes(b'tampered')
        metadata['products'][0].update(bytes=8, sha256=sha256(b'tampered').hexdigest())
    elif tamper == 'archive':
        with archive.open('ab') as stream:
            stream.write(b'tampered')
    else:
        metadata['source_commit'] = '0'*40
    with pytest.raises(ValueError):
        bridge.product_paths(root, metadata, archive)


@pytest.fixture
def live(tmp_path, monkeypatch):
    response = bridge.encoded(dict(model='text-embedding-3-small',
        data=[dict(index=0, embedding=[1.]+[0.]*1535)], usage=dict(prompt_tokens=1, total_tokens=1)))
    requests = [ProviderRequest('openai', 'text-embedding-3-small', bridge.encoded(dict(
        model='text-embedding-3-small', dimensions=1536, encoding_format='float', input=['tiny'])),
        f'{index:064x}') for index in range(39)]
    with EvaluationJournal(tmp_path/'recordings', evidence_kind='live') as journal:
        for request in requests:
            journal.complete(journal.begin(request, 10), response)
        journal.finish()
    provenance = dict(packet_sha256='a'*64)
    values = {
        'run-binding.json': dict(revision='ECR-r1', mode='live', packet=provenance,
            runtime_identity_sha256=bridge.BASE_IDENTITY),
        'provider-accounting.json': dict(evidence_kind='live', failed=False, cleanup_verified=True,
            budget=dict(attempts=39, pending=0), journal=dict(evidence_kind='live', attempts=39,
                completed=39, pending=0, failed=False, sealed=True)),
        'python_live.json': dict(runtime='python', kind='provider'),
    }
    for name, value in values.items():
        (tmp_path/name).write_bytes(bridge.encoded(value))
    monkeypatch.setattr(bridge, 'RETAINED', {name: sha256((tmp_path/name).read_bytes()).hexdigest()
        for name in (*values, 'recordings/seal.json')})
    return tmp_path, dict(provenance=provenance), requests


@pytest.mark.parametrize('tamper', ['response', 'incomplete', 'binding', 'seal'])
def test_retained_live_rejects_tamper_and_incomplete_journal(live, tamper):
    root, bound, _ = live
    tape, _ = bridge.retained(root, bound)
    assert len(tape) == 39
    if tamper == 'response':
        (root/'recordings/039.response').write_bytes(b'{}')
    elif tamper == 'incomplete':
        (root/'recordings/039.complete.json').unlink()
    elif tamper == 'binding':
        bound = dict(provenance=dict(packet_sha256='b'*64))
    else:
        (root/'recordings/seal.json').write_bytes(b'{}')
    with pytest.raises((ValueError, ProviderAdapterError)):
        bridge.retained(root, bound)


def test_strict_tape_rejects_changed_key_omission_and_extra_call(live):
    root, bound, requests = live
    tape, _ = bridge.retained(root, bound)
    async def consume():
        replay = ReplaySend(tape)
        with pytest.raises(ProviderAdapterError):
            await replay(requests[1], deadline=time.monotonic()+5, max_response_bytes=20000)
        for request in requests[:-1]:
            await replay(request, deadline=time.monotonic()+5, max_response_bytes=20000)
        with pytest.raises(ProviderAdapterError):
            replay.assert_complete()
        await replay(requests[-1], deadline=time.monotonic()+5, max_response_bytes=20000)
        replay.assert_complete()
        with pytest.raises(ProviderAdapterError):
            await replay(requests[-1], deadline=time.monotonic()+5, max_response_bytes=20000)
    asyncio.run(consume())


def test_normalization_only_allows_timing_changes(monkeypatch):
    import run_release_evaluation as execution
    monkeypatch.setattr(execution, 'check_observation', lambda *args, **kwargs: None)
    original = dict(revision='EVX-r1', runtime='python', kind='provider', receipts=[{} for _ in range(5)],
        rows=[dict(latency_ms=1, result=dict(status='partial', usage=dict(
            stage_durations=[dict(duration_ms=1)]))) for _ in range(30)])
    observed = deepcopy(original)
    observed['runtime'], observed['kind'] = 'node', 'replay'
    observed['rows'][0]['latency_ms'] = 20
    observed['rows'][0]['result']['usage']['stage_durations'][0]['duration_ms'] = 50
    bridge.compare({}, original, observed, 'node', 'replay', None)
    observed['rows'][0]['result']['status'] = 'sufficient'
    with pytest.raises(ValueError):
        bridge.compare({}, original, observed, 'node', 'replay', None)
