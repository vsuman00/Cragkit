"""Closed native-result protocol tests; these do not exercise PostgreSQL."""
from copy import deepcopy
import json
from pathlib import Path
import re
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_qdrant_guard_authority as checker
import qdrant_guard_authority_cases as cases


class Text(str):
    pass


class Items(list):
    pass


class Record(dict):
    pass


def result(runtime='python'):
    return dict(runtime=runtime, checks=list(cases.CHECKS),
                proof_scope='profile4_authority_admission_only', source_queries=6,
                denied_source_queries=0)


def failure(**changes):
    value = dict(ok=False, step=0, error='UnsupportedCapability')
    value.update(changes)
    return value


def cleanup(**changes):
    value = failure(error='cleanup_failed', primary='UnsupportedCapability',
                    cleanup=[dict(operation='catalog_restore', outcome='ProviderUnavailable')])
    value.update(changes)
    return value


def test_exact_eight_checks_and_closed_labels_describe_authority_only():
    assert type(cases.CHECKS) is tuple and len(cases.CHECKS) == len(set(cases.CHECKS)) == 8
    assert all(type(item) is str and re.fullmatch('[a-z][a-z0-9_]{0,127}', item)
               for item in cases.CHECKS)
    assert type(cases.ERRORS) is tuple and len(cases.ERRORS) == len(set(cases.ERRORS))
    assert 'cleanup_failed' in cases.ERRORS and 'internal' in cases.ERRORS
    assert checker.validate_result(result(), 'python')['proof_scope'] == 'profile4_authority_admission_only'


@pytest.mark.parametrize('runtime', ['python', 'typescript'])
def test_valid_result_is_a_detached_closed_copy(runtime):
    value = result(runtime)
    accepted = checker.validate_result(value, runtime)
    assert accepted == value and accepted is not value
    assert accepted['checks'] is not value['checks']
    value['checks'].clear()
    value['source_queries'] = 100
    assert accepted == result(runtime)
    assert 'private' not in json.dumps(accepted)


@pytest.mark.parametrize('field,value', [
    ('runtime', 'other'), ('runtime', b'python'), ('runtime', Text('python')),
    ('checks', tuple(cases.CHECKS)), ('checks', Items(cases.CHECKS)),
    ('checks', [Text(item) for item in cases.CHECKS]),
    ('checks', list(reversed(cases.CHECKS))), ('checks', list(cases.CHECKS[:-1])),
    ('checks', [*cases.CHECKS, cases.CHECKS[-1]]),
    ('checks', [cases.CHECKS[0]]*8), ('checks', [item.encode() for item in cases.CHECKS]),
    ('proof_scope', 'physical_security_settlement'),
    ('proof_scope', Text('profile4_authority_admission_only')),
    ('source_queries', True), ('source_queries', 6.0), ('source_queries', 5),
    ('denied_source_queries', False), ('denied_source_queries', 0.0), ('denied_source_queries', 1),
])
def test_result_rejects_wrong_order_scope_counts_or_non_native_scalars(field, value):
    raw = result();raw[field] = value
    with pytest.raises(RuntimeError): checker.validate_result(raw, 'python')


@pytest.mark.parametrize('raw', [None, [], Record(result()),
    {**result(), 'private_sql': b'PRIVATE DATABASE BYTES'},
    {key: value for key, value in result().items() if key != 'source_queries'}])
def test_result_rejects_open_or_missing_fields_and_non_records(raw):
    with pytest.raises(RuntimeError) as caught: checker.validate_result(raw, 'python')
    assert 'PRIVATE' not in str(caught.value)


@pytest.mark.parametrize('step', [0, 1, 7, 8])
@pytest.mark.parametrize('label', cases.ERRORS)
def test_plain_failure_accepts_only_closed_non_cleanup_labels(step, label):
    if label == 'cleanup_failed':
        with pytest.raises(RuntimeError): checker.failure_observation(failure(step=step, error=label))
    else:
        value = failure(step=step, error=label)
        assert checker.failure_observation(value) == value


@pytest.mark.parametrize('field,value', [
    ('ok', True), ('ok', 0), ('ok', None), ('step', True), ('step', False),
    ('step', -1), ('step', 9), ('step', 0.0), ('step', '0'),
    ('error', 'PRIVATE SQL'), ('error', b'UnsupportedCapability'),
    ('error', Text('UnsupportedCapability')),
])
def test_failure_rejects_non_native_or_out_of_range_scalars(field, value):
    raw = failure();raw[field] = value
    with pytest.raises(RuntimeError): checker.failure_observation(raw)


@pytest.mark.parametrize('raw', [None, [], Record(failure()),
    {**failure(), 'query': 'PRIVATE SQL'}, {**failure(), 'bytes': b'PRIVATE'},
    {key: value for key, value in failure().items() if key != 'step'}])
def test_failure_rejects_missing_extra_or_private_fields(raw):
    with pytest.raises(RuntimeError) as caught: checker.failure_observation(raw)
    assert 'PRIVATE' not in str(caught.value)


@pytest.mark.parametrize('operation', [
    'catalog_restore', 'reader_pool_close', 'operator_pool_close', 'factory_pool_close'])
@pytest.mark.parametrize('primary', [None, 'UnsupportedCapability', 'CancelledError', 'internal'])
def test_cleanup_operation_whitelist_and_primary_are_preserved(operation, primary):
    value = cleanup(primary=primary, cleanup=[dict(operation=operation, outcome='DeadlineExceeded')])
    assert checker.failure_observation(value) == value


@pytest.mark.parametrize('changes', [
    {'primary': 'cleanup_failed'}, {'primary': 'PRIVATE'}, {'primary': b'internal'},
    {'primary': Text('internal')}, {'cleanup': []}, {'cleanup': [{}]*9},
    {'cleanup': ({'operation': 'catalog_restore', 'outcome': 'internal'},)},
    {'cleanup': Items([{'operation': 'catalog_restore', 'outcome': 'internal'}])},
    {'cleanup': [{'operation': 'private_cleanup', 'outcome': 'internal'}]},
    {'cleanup': [{'operation': Text('catalog_restore'), 'outcome': 'internal'}]},
    {'cleanup': [{'operation': b'catalog_restore', 'outcome': 'internal'}]},
    {'cleanup': [{'operation': 'catalog_restore', 'outcome': Text('internal')}]},
    {'cleanup': [{'operation': 'catalog_restore', 'outcome': b'internal'}]},
    {'cleanup': [{'operation': 'catalog_restore', 'outcome': 'PRIVATE'}]},
    {'cleanup': [{'operation': 'catalog_restore', 'outcome': 'internal', 'sql': 'PRIVATE'}]},
    {'cleanup': [Record(operation='catalog_restore', outcome='internal')]},
    {'cleanup': [{'operation': 'catalog_restore'}]}, {'private': b'PRIVATE'},
])
def test_cleanup_rejects_recursive_primary_unknown_operations_and_open_diagnostics(changes):
    value = cleanup(**changes)
    with pytest.raises(RuntimeError) as caught: checker.failure_observation(value)
    assert 'PRIVATE' not in str(caught.value)


@pytest.mark.parametrize('missing', ['primary', 'cleanup'])
def test_cleanup_requires_all_its_closed_fields(missing):
    value = cleanup();del value[missing]
    with pytest.raises(RuntimeError): checker.failure_observation(value)


@pytest.mark.parametrize('value', [failure(), cleanup()])
def test_failure_validation_and_exception_constructor_both_isolate_nested_input(value):
    expected = deepcopy(value)
    accepted = checker.failure_observation(value)
    exception = cases.NativeGuardAuthorityFailure(value)
    value['step'] = 8
    if 'cleanup' in value: value['cleanup'][0]['operation'] = 'PRIVATE'
    assert accepted == expected
    assert exception.observation == expected
    assert accepted is not value and exception.observation is not value
    assert str(exception) == 'guard_authority_native_case_failed'
    assert 'PRIVATE' not in str(exception)


@pytest.mark.parametrize('value', [None, Record(failure()), failure(step=True),
    failure(sql='PRIVATE'), cleanup(primary='cleanup_failed'),
    cleanup(cleanup=[dict(operation='unknown', outcome='internal')])])
def test_exception_constructor_cannot_bypass_closed_failure_protocol(value):
    with pytest.raises(RuntimeError) as caught: cases.NativeGuardAuthorityFailure(value)
    assert 'PRIVATE' not in str(caught.value)


@pytest.mark.parametrize('existing_diagnostic', [False, True])
def test_main_refuses_unowned_artifacts_without_changing_evidence(tmp_path, monkeypatch, capsys, existing_diagnostic):
    retained = tmp_path/'results.json'
    retained.write_bytes(b'original native evidence\n')
    diagnostic = tmp_path/'failure-locations.json'
    if existing_diagnostic: diagnostic.write_bytes(b'original locations\n')
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    monkeypatch.setattr(checker, 'PostgresSourceFixture',
                        lambda *args, **kwargs: pytest.fail('fixture must not start'))
    code = checker.main(['--postgres-bin', str(tmp_path/'postgres'),
                         '--artifacts-dir', str(tmp_path), '--allow-local-processes'])
    assert code == 1
    assert json.loads(capsys.readouterr().out)['ok'] is False
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_auxiliary_diagnostic_write_failure_preserves_closed_primary(tmp_path, monkeypatch, capsys):
    original = failure(step=3, error='UnsupportedCapability')
    def fail_fixture(*args, **kwargs):
        raise cases.NativeGuardAuthorityFailure(original)
    monkeypatch.setattr(checker, 'PostgresSourceFixture', fail_fixture)
    write_text = Path.write_text
    def fail_diagnostic(path, *args, **kwargs):
        if path.name == 'failure-locations.json': raise OSError('PRIVATE AUXILIARY PATH')
        return write_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'write_text', fail_diagnostic)
    directory = tmp_path/'new'
    assert checker.main(['--postgres-bin', str(tmp_path/'postgres'), '--artifacts-dir', str(directory),
                         '--runtime', 'python', '--allow-local-processes']) == 1
    output = capsys.readouterr().out
    assert 'PRIVATE' not in output
    assert json.loads(output)['native'] == original
    assert not (directory/'results.json').exists()
