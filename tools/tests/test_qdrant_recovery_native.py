"""Closed native evidence envelopes and real-commit fault-wrapper ordering."""
import asyncio
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_qdrant_recovery import failure_observation, validate_result
from qdrant_recovery_cases import CHECKS, _AckConnection, NativeRecoveryFailure, recovery_input
from cragkit._qdrant_writer_contract import prepare_stage


def test_two_document_input_has_distinct_valid_claims_and_explicit_trusted_scopes():
    value = recovery_input()
    assert prepare_stage(value['stage']).member_count == prepare_stage(value['second_stage']).member_count == 2
    assert value['scope']['tenant_id'] != value['second_scope']['tenant_id']
    assert value['second_scope']['tenant_id'] == value['second_stage']['manifest']['tenant_id']
    assert not {p['id'] for p in value['expected_points']} & {p['id'] for p in value['second_points']}
    assert len(json.dumps(value).encode()) < 524288
    assert value['collection_config']['optimizers_config']['prevent_unoptimized'] is False


def test_native_success_requires_all_cases_and_does_not_claim_publication():
    value = dict(runtime='python', checks=list(CHECKS), proof_scope='durable_recovery_settlement_only')
    assert validate_result(value, 'python') == value
    for changed in [dict(value, checks=value['checks'][:-1]), dict(value, runtime='typescript'),
            dict(value, proof_scope='publication_complete'), dict(value, source='private')]:
        with pytest.raises(RuntimeError, match='recovery_native_result_shape'):
            validate_result(changed, 'python')


def test_closed_failure_envelope_rejects_private_content_and_preserves_cleanup_failures():
    value = dict(ok=False, step=15, error='cleanup_failed', primary='ProviderUnavailable',
        cleanup=[dict(operation='supervisor_pool_close', outcome='internal'),
                 dict(operation='listener_close', outcome='DeadlineExceeded')])
    observed = failure_observation(value)
    value['cleanup'].clear()
    assert len(observed['cleanup']) == 2
    for changed in [dict(ok=False, step=True, error='internal'), dict(ok=False, step=len(CHECKS)+1, error='internal'),
            dict(ok=False, step=0, error='internal', message='private SQL'), dict(observed, primary=[]),
            dict(observed, cleanup=[dict(operation='private endpoint', outcome='internal')])]:
        with pytest.raises(RuntimeError, match='recovery_native_failure_shape'):
            failure_observation(changed)
    assert str(NativeRecoveryFailure(observed)) == 'recovery_native_case_failed'


def test_ack_injector_waits_for_actual_delegated_commit_before_withholding_acknowledgment():
    async def check():
        events = []
        class Connection:
            async def execute(self, sql, params=(), **options):
                events.append('actual_update')
                return object()
            def transaction(self):
                class Transaction:
                    async def __aenter__(self): events.append('actual_begin')
                    async def __aexit__(self, kind, error, traceback): events.append('actual_commit')
                return Transaction()
        state = dict(armed=True, fired=False, boundary_sealed=False, open_updates=0, sql_calls=0,
            assert_sealed=lambda: events.append('native_seal_observed'))
        connection = _AckConnection(Connection(), state)
        with pytest.raises(ConnectionError, match='injected_committed_ack_loss'):
            async with connection.transaction():
                await connection.execute("UPDATE cragkit_qdrant.backend_instances SET state='open'")
        assert events == ['actual_begin', 'actual_update', 'actual_commit', 'native_seal_observed']
        assert state['fired'] and state['boundary_sealed'] and state['open_updates'] == 1
        assert not state['armed']
    asyncio.run(check())
