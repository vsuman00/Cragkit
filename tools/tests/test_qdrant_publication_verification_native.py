"""Closed native F1 evidence framing; ordinary receipts never claim publication."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_qdrant_publication_verification import validate_result, failure_observation
from qdrant_publication_verification_cases import CHECKS, NativePublicationVerificationFailure


def test_success_cannot_claim_publication_or_omit_native_cases():
    result = dict(runtime='python', checks=list(CHECKS), proof_scope='ordinary_readback_only',
        normalized_witness_sha256='a' * 64)
    assert validate_result(result, 'python') == result
    for changed in [dict(result, checks=result['checks'][:-1]), dict(result, runtime='typescript'),
            dict(result, proof_scope='published'), dict(result, canonical_text='private'),
            dict(result, normalized_witness_sha256='not-a-digest')]:
        with pytest.raises(RuntimeError, match='publication_verification_native_result_shape'):
            validate_result(changed, 'python')


def test_failure_protocol_rejects_private_content_and_preserves_cleanup():
    failure = dict(ok=False, step=3, error='cleanup_failed', primary='IntegrityViolation',
        cleanup=[dict(operation='verifier_close', outcome='ProviderUnavailable'),
                 dict(operation='listener_close', outcome='internal')])
    observed = failure_observation(failure)
    failure['cleanup'].clear()
    assert len(observed['cleanup']) == 2
    for changed in [dict(ok=False, step=True, error='internal'),
            dict(ok=False, step=len(CHECKS) + 1, error='internal'),
            dict(ok=False, step=0, error='internal', message='private'),
            dict(observed, cleanup=[dict(operation='private-body', outcome='internal')]),
            dict(observed, primary=[])]:
        with pytest.raises(RuntimeError, match='publication_verification_native_failure_shape'):
            failure_observation(changed)
    assert 'private' not in json.dumps(observed)


def test_exception_uses_only_closed_observation():
    failure = NativePublicationVerificationFailure(2, RuntimeError('private_source_or_credential'))
    assert str(failure) == 'publication_verification_native_case_failed'
    assert failure.observation == dict(step=2, error='internal')
    assert failure_observation(dict(ok=False, **failure.observation)) == dict(ok=False, step=2, error='internal')
