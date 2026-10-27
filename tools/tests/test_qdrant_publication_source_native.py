"""Closed content-free evidence boundaries for public source acceptance."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_qdrant_publication_source import (
    failure_observation, publication_source_input, validate_result,
)
from qdrant_publication_source_cases import CHECKS


def test_successor_keeps_source_and_original_pointer_fences():
    from cragkit._qdrant_writer_contract import prepare_stage
    from cragkit.contracts import RetrievalRequest
    inputs = publication_source_input()
    first, second = inputs['stage'], inputs['successor']
    assert len(json.dumps(inputs).encode()) < 1048576
    assert prepare_stage(first).member_count == prepare_stage(second).member_count == 2
    assert first['canonical_text'] == second['canonical_text']
    assert first['manifest']['source_sha256'] == second['manifest']['source_sha256']
    assert second['intent']['expected_active_generation_id'] == first['manifest']['generation_id']
    assert second['intent']['initial_authorization'] is None
    assert {m['point_id'] for m in first['manifest']['members']}.isdisjoint(
        m['point_id'] for m in second['manifest']['members'])
    request = RetrievalRequest.model_validate(inputs['request'])
    assert request.collection == first['manifest']['collection']
    assert request.limits.max_candidates == 8
    assert request.limits.max_provider_calls == 0


def test_success_accepts_only_complete_content_free_source_evidence():
    value = dict(runtime='python', checks=list(CHECKS),
        proof_scope='public_source_publication_only', source_observations_sha256='a' * 64)
    assert validate_result(value, 'python') == value
    for changed in (dict(value, checks=value['checks'][:-1]),
            dict(value, runtime='typescript'), dict(value, proof_scope='process_crash_recovery'),
            dict(value, source_text='private'), dict(value, source_observations_sha256='bad')):
        with pytest.raises(RuntimeError, match='publication_source_native_result_shape'):
            validate_result(changed, 'python')


def test_failures_preserve_primary_and_cleanup_without_free_text():
    value = dict(ok=False, step=4, error='cleanup_failed', primary='ProviderUnavailable',
        cleanup=[dict(operation='request_close', outcome='DeadlineExceeded'),
                 dict(operation='publish_drain', outcome='internal')])
    saved = failure_observation(value)
    value['cleanup'].clear()
    assert len(saved['cleanup']) == 2
    variants = [dict(ok=False, step=True, error='internal'),
        dict(ok=False, step=len(CHECKS) + 1, error='internal'),
        dict(ok=False, step=0, error='arbitrary-detail'),
        dict(ok=False, step=0, error='ProviderUnavailable', text='private'),
        dict(saved, primary=[]),
        dict(saved, cleanup=[dict(operation='private-source', outcome='internal')])]
    for changed in variants:
        with pytest.raises(RuntimeError, match='publication_source_native_failure_shape'):
            failure_observation(deepcopy(changed))
