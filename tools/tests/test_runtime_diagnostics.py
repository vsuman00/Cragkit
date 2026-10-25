"""D-r1 diagnostics contract tests using synthetic exceptions only."""
import asyncio
from concurrent.futures import CancelledError as FutureCancelledError
import importlib.util
import json
from pathlib import Path
import sys

import pytest

SPEC = importlib.util.spec_from_file_location(
    'runtime_diagnostics', Path(__file__).resolve().parents[1] / 'runtime_diagnostics.py')
assert SPEC and SPEC.loader
DIAGNOSTICS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DIAGNOSTICS
SPEC.loader.exec_module(DIAGNOSTICS)

OPERATIONS = (
    'primary', 'runtime_close', 'child_stop', 'admin_close', 'admin_connect',
    'schema_restore', 'fixture_transaction', 'policy_drop', 'privilege_revoke',
    'row_delete', 'role_drop', 'verify_inventory', 'lock_acquire', 'lock_release',
    'journal_write', 'journal_read', 'journal_remove', 'cleanup_budget', 'unknown',
)
STAGES = (
    'configuration', 'admin_connect', 'lexical_fixture_locale', 'fixture_setup',
    'hybrid_evaluation', 'dense_retrieval', 'vector_generations', 'python_ingestion',
    'typescript_runtime', 'runtime_login', 'scope_filters', 'deadline_cancellation',
    'schema_rejection', 'deadline_query_starting', 'deadline_query_observation',
    'deadline_query_completion', 'deadline_query_fresh_scope_reuse',
    'cancel_query_starting', 'cancel_query_observation', 'cancel_query_completion',
    'cancel_query_fresh_scope_reuse', 'recovery', 'unknown',
)
CANARIES = (
    'synthetic-secret-canary', "SELECT private_canary FROM secret_table",
    'postgresql://synthetic_user:synthetic_password@invalid.example/private_db',
    'private-query-canary',
)


class OpaqueError(Exception):
    def __str__(self):
        raise AssertionError('exception str must not be called')

    def __repr__(self):
        raise AssertionError('exception repr must not be called')


class OpaqueString(str):
    def __str__(self):
        raise AssertionError('string conversion must not be called')

    def __repr__(self):
        raise AssertionError('string repr must not be called')

    def __hash__(self):
        raise AssertionError('string subclass hashing must not be called')

    def __eq__(self, other):
        raise AssertionError('string subclass equality must not be called')


def describe(error, operation='runtime_close', stage='recovery'):
    return DIAGNOSTICS.describe_error(error, operation=operation, stage=stage)


def test_record_shape_and_all_allowlisted_labels():
    for operation in OPERATIONS:
        assert describe(RuntimeError(), operation=operation) == {
            'operation': operation, 'stage': 'recovery',
            'category': 'operation', 'sqlstate': None,
        }
    for stage in STAGES:
        assert describe(RuntimeError(), stage=stage)['stage'] == stage


@pytest.mark.parametrize('label', [None, 3, [], {}, 'PRIVATE', 'runtime_close\n',
                                    OpaqueString('runtime_close'), object()])
def test_untrusted_labels_are_unknown_without_coercion(label):
    result = describe(OpaqueError(*CANARIES), operation=label, stage=label)
    assert result == {'operation': 'unknown', 'stage': 'unknown',
                      'category': 'operation', 'sqlstate': None}


@pytest.mark.parametrize(('error', 'category'), [
    (asyncio.CancelledError(*CANARIES), 'cancelled'),
    (FutureCancelledError(*CANARIES), 'cancelled'),
    (TimeoutError(*CANARIES), 'timeout'),
    (ConnectionError(*CANARIES), 'connection'),
    (ValueError(*CANARIES), 'validation'),
    (TypeError(*CANARIES), 'validation'),
    (OpaqueError(*CANARIES), 'operation'),
    (KeyboardInterrupt(*CANARIES), 'operation'),
])
def test_native_exception_categories_preserve_failure_kind(error, category):
    assert describe(error)['category'] == category


@pytest.mark.parametrize(('state', 'category'), [
    ('08006', 'connection'), ('23505', 'database'), ('57014', 'database'),
    ('ABCDE', 'database'), ('00000', 'database'),
])
def test_exact_valid_sqlstate_is_the_only_database_detail(state, category):
    error = OpaqueError(*CANARIES)
    error.sqlstate = state
    assert describe(error) == {'operation': 'runtime_close', 'stage': 'recovery',
                               'category': category, 'sqlstate': state}


@pytest.mark.parametrize('state', [None, 23505, b'23505', '', '2350', '235050',
                                    'abcde', '23_05', '23\n05', '２３５０５',
                                    '23505\n', OpaqueString('23505'), [], {}])
def test_malformed_sqlstate_is_discarded_without_conversion(state):
    error = OpaqueError(*CANARIES)
    error.sqlstate = state
    assert describe(error)['sqlstate'] is None
    assert describe(error)['category'] == 'operation'


@pytest.mark.parametrize('raised', [RuntimeError(*CANARIES),
                                     asyncio.CancelledError(*CANARIES),
                                     KeyboardInterrupt(*CANARIES)])
def test_raising_sqlstate_property_cannot_break_diagnostics(raised):
    class BrokenState(OpaqueError):
        @property
        def sqlstate(self):
            raise raised
    assert describe(BrokenState(*CANARIES))['sqlstate'] is None


def test_native_cancellation_and_timeout_win_over_database_state():
    for error, expected in [(asyncio.CancelledError(), 'cancelled'),
                            (TimeoutError(), 'timeout'), (ConnectionError(), 'connection')]:
        error.sqlstate = '23505'
        assert describe(error)['category'] == expected


def test_opaque_exception_metadata_is_excluded_from_json_and_failure_message():
    error = OpaqueError(*CANARIES)
    error.query, error.dsn, error.diag, error.resource_name = CANARIES
    failure = DIAGNOSTICS.CleanupFailure([('admin_close', error)], primary=error,
                                         stage='recovery')
    assert str(failure) == 'cleanup_failed'
    assert failure.args == ('cleanup_failed',)
    payload = failure.to_dict()
    assert set(payload) == {'code', 'primary', 'cleanup'}
    assert payload['code'] == 'cleanup_failed'
    assert payload['primary'] == {'operation': 'primary', 'stage': 'recovery',
                                  'category': 'operation', 'sqlstate': None}
    assert payload['cleanup'] == [{'operation': 'admin_close', 'stage': 'recovery',
                                   'category': 'operation', 'sqlstate': None}]
    serialized = json.dumps(payload)
    for canary in CANARIES:
        assert canary not in serialized
    assert 'OpaqueError' not in serialized


def test_original_and_multiple_cleanup_failures_remain_separate():
    original = OpaqueError(*CANARIES)
    original.sqlstate = '23505'
    failure = DIAGNOSTICS.CleanupFailure(
        [('cleanup_budget', TimeoutError()), ('admin_close', ConnectionError())],
        primary=original, stage='fixture_setup')
    payload = failure.to_dict()
    assert payload['primary']['category'] == 'database'
    assert payload['primary']['sqlstate'] == '23505'
    assert [record['operation'] for record in payload['cleanup']] == [
        'cleanup_budget', 'admin_close']
    assert [record['category'] for record in payload['cleanup']] == ['timeout', 'connection']
    assert all(record['stage'] == 'fixture_setup' for record in payload['cleanup'])


def test_cleanup_cancellation_is_an_error_record_and_primary_is_optional():
    failure = DIAGNOSTICS.CleanupFailure([('child_stop', asyncio.CancelledError())])
    assert isinstance(failure, BaseException)
    assert failure.to_dict() == {
        'code': 'cleanup_failed', 'primary': None,
        'cleanup': [{'operation': 'child_stop', 'stage': 'unknown',
                     'category': 'cancelled', 'sqlstate': None}],
    }


def test_constructor_and_each_serialization_take_detached_snapshots():
    error = OpaqueError()
    error.sqlstate = '23505'
    pair = ['admin_close', error]
    failures = [pair]
    failure = DIAGNOSTICS.CleanupFailure(failures, primary=error, stage='recovery')
    error.sqlstate = '08006'
    pair[:] = ['runtime_close', TimeoutError()]
    failures.clear()
    first = failure.to_dict()
    first['primary']['sqlstate'] = None
    first['cleanup'][0]['operation'] = 'changed'
    first['cleanup'].append({'arbitrary': 'value'})
    second = failure.to_dict()
    assert second['primary']['sqlstate'] == '23505'
    assert second['cleanup'] == [{'operation': 'admin_close', 'stage': 'recovery',
                                  'category': 'database', 'sqlstate': '23505'}]
    assert json.loads(json.dumps(second)) == second


def test_sixteen_cleanup_failures_are_accepted_in_order():
    pairs = tuple((operation, RuntimeError()) for operation in OPERATIONS[:16])
    payload = DIAGNOSTICS.CleanupFailure(pairs).to_dict()
    assert [record['operation'] for record in payload['cleanup']] == list(OPERATIONS[:16])


def test_sqlstate_descriptor_cannot_mutate_validated_input_pairs():
    failures = []

    class MutatingState(OpaqueError):
        @property
        def sqlstate(self):
            failures[1][:] = ['role_drop', TimeoutError()]
            failures.extend([('row_delete', RuntimeError())] * 17)
            return '23505'

    failures.extend([['admin_close', MutatingState()],
                     ['runtime_close', ConnectionError()]])
    payload = DIAGNOSTICS.CleanupFailure(failures).to_dict()
    assert len(payload['cleanup']) == 2
    assert [record['operation'] for record in payload['cleanup']] == [
        'admin_close', 'runtime_close']
    assert [record['category'] for record in payload['cleanup']] == ['database', 'connection']


@pytest.mark.parametrize('failures', [None, [], (), {}, 'private-query-canary',
    [None], [('admin_close',)], [('admin_close', RuntimeError(), None)],
    [('admin_close', None)], [('admin_close', object())],
    [('admin_close', RuntimeError())] * 17,
])
def test_malformed_or_unbounded_cleanup_data_has_fixed_error(failures):
    with pytest.raises(ValueError) as caught:
        DIAGNOSTICS.CleanupFailure(failures)
    assert caught.value.args == ('invalid_cleanup_failures',)


def test_nonexception_primary_has_fixed_error_without_rendering():
    with pytest.raises(ValueError) as caught:
        DIAGNOSTICS.CleanupFailure([('admin_close', RuntimeError())],
                                   primary=OpaqueString('private-query-canary'))
    assert caught.value.args == ('invalid_cleanup_failures',)


def test_container_subclasses_are_rejected_without_iteration():
    class HostileList(list):
        def __len__(self):
            raise AssertionError('untrusted length must not be called')

        def __iter__(self):
            raise AssertionError('untrusted iteration must not be called')

    for failures in (HostileList(), [HostileList()]):
        with pytest.raises(ValueError) as caught:
            DIAGNOSTICS.CleanupFailure(failures)
        assert caught.value.args == ('invalid_cleanup_failures',)


def test_exception_class_descriptor_is_never_consulted_for_classification():
    class HostileClassError(OpaqueError):
        @property
        def __class__(self):
            raise AssertionError('private-query-canary')

    error = HostileClassError(*CANARIES)
    assert describe(error) == {'operation': 'runtime_close', 'stage': 'recovery',
                               'category': 'operation', 'sqlstate': None}
    payload = DIAGNOSTICS.CleanupFailure([('admin_close', error)], primary=error).to_dict()
    assert payload['primary']['category'] == 'operation'
    assert payload['cleanup'][0]['category'] == 'operation'
    assert all(canary not in json.dumps(payload) for canary in CANARIES)


def test_nonexception_class_descriptor_is_never_consulted_for_validation():
    class HostileClass:
        @property
        def __class__(self):
            raise AssertionError('private-query-canary')

        def __str__(self):
            raise AssertionError('private-query-canary')

        def __repr__(self):
            raise AssertionError('private-query-canary')

    malformed = HostileClass()
    for invoke in (
        lambda: describe(malformed),
        lambda: DIAGNOSTICS.CleanupFailure([('admin_close', malformed)]),
        lambda: DIAGNOSTICS.CleanupFailure([('admin_close', RuntimeError())],
                                          primary=malformed),
    ):
        with pytest.raises(ValueError) as caught:
            invoke()
        assert caught.value.args == ('invalid_cleanup_failures',)
