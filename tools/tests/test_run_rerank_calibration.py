"""Offline response mapping and live-command admission regressions."""
import importlib.util
import asyncio
import json
from pathlib import Path
import sys

import pytest

SPEC=importlib.util.spec_from_file_location('run_rerank_calibration',Path(__file__).resolve().parents[1]/'run_rerank_calibration.py')
MOD=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def test_response_mapping_preserves_raw_scores_and_unknown_billing():
    raw=json.dumps(dict(results=[dict(index=1,relevance_score=-3),dict(index=0,relevance_score=2)]))
    scores,billed=MOD.normalize(raw,[dict(evidence_id='a'),dict(evidence_id='b')])
    assert scores==[dict(candidate_id='a',raw_score=2),dict(candidate_id='b',raw_score=-3)]
    assert billed is None


@pytest.mark.parametrize('rows', [[],[dict(index=0,relevance_score=True)],
    [dict(index=True,relevance_score=1)],[dict(index=1,relevance_score=1)],
    [dict(index=0,relevance_score=float('nan'))],
    [dict(index=0,relevance_score=1),dict(index=0,relevance_score=2)]])
def test_invalid_response_mapping_cannot_become_a_success(rows):
    with pytest.raises((ValueError,KeyError,TypeError)):
        MOD.normalize(json.dumps(dict(results=rows)),[dict(evidence_id='a')])


def test_duplicate_json_keys_rejected():
    with pytest.raises(ValueError):
        MOD.normalize('{"results":[],"results":[]}',[])


def test_live_dispatch_is_refused_without_explicit_flag(monkeypatch,capsys):
    monkeypatch.setattr(sys,'argv',['run_rerank_calibration.py'])
    assert MOD.main()==2
    assert json.loads(capsys.readouterr().out)['code']=='explicit_live_opt_in_required'


def test_run_imports_renamed_calibration_before_reading_baseline(tmp_path):
    baseline = tmp_path / 'missing baseline.json'
    with pytest.raises(FileNotFoundError) as caught:
        asyncio.run(MOD.run(baseline, tmp_path / 'unused output.json'))
    assert caught.value.filename == str(baseline)


@pytest.mark.parametrize('kind',['credential','http'])
def test_failed_child_persists_redacted_actual_call_observation(tmp_path,monkeypatch,kind):
    monkeypatch.syspath_prepend(str(MOD.ROOT/'tools'))
    import check_cohere_reranking as probe
    request_path,response_path=tmp_path/'request.json',tmp_path/'response.json'
    request_path.write_text(json.dumps(dict(model='rerank-v5.0-fast',query='synthetic',
        documents=['public synthetic'],top_n=1,max_tokens_per_doc=4096)))
    def key():
        if kind=='credential':raise probe.ProbeFailure('credential_invalid')
        return 'synthetic-test-only'
    def failed(body,key,timeout,observation):
        observation.update(provider_calls=1,http_status=401)
        raise probe.ProbeFailure('provider_http_status')
    monkeypatch.setattr(probe,'read_key',key)
    monkeypatch.setattr(probe,'request',failed)
    assert MOD.dispatch(request_path,response_path) is False
    outcome=json.loads(response_path.read_text())
    assert outcome['state']=='failed'
    assert outcome['observation']['provider_calls']==(0 if kind=='credential' else 1)
    assert 'synthetic-test-only' not in response_path.read_text()


@pytest.mark.parametrize('change',[dict(documents=['x']*3),dict(top_n=True),dict(model='other'),dict(query='x'*8193)])
def test_payload_bounds_preflight_before_private_key_read(change):
    payload=dict(model='rerank-v5.0-fast',query='synthetic',documents=['public'],top_n=1,max_tokens_per_doc=4096)
    payload.update(change)
    with pytest.raises(ValueError):MOD.validate_payload(payload)
