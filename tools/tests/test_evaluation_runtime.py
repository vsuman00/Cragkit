"""Tiny injected execution-identity fixtures; no original candidate build or installation."""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import subprocess

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evaluation_runtime as runtime


@pytest.fixture
def layout(tmp_path, monkeypatch):
    root = tmp_path/'checkout'
    root.mkdir()
    paths = {}
    for category in ('node_dist', 'node_dependencies', 'python_dependencies', 'python_stdlib',
            'npm_toolchain', 'checkout_bytecode'):
        directory = root/category
        directory.mkdir()
        (directory/'file').write_bytes(category.encode())
        paths[category] = (directory, frozenset())
    executable = root/'python'
    executable.write_bytes(b'synthetic executable')
    token = root/'artifacts/tokenizers/cl100k_base.tiktoken'
    token.parent.mkdir(parents=True)
    token.write_bytes(b'synthetic pinned tokenizer')
    monkeypatch.setattr(runtime, 'TOKENIZER_SHA256', sha256(token.read_bytes()).hexdigest())
    candidate = dict(source_commit='a'*40, package_tree='b'*40, configuration_sha256='c'*64)
    versions = dict(python='3.14.6', node='26.5.0', npm='11.17.0', typescript='7.0.2',
        python_bytecode_writes=False)
    monkeypatch.setattr(runtime, '_candidate', lambda given: ({}, dict(candidate)))
    monkeypatch.setattr(runtime, '_versions', lambda given, configuration: dict(versions))
    monkeypatch.setattr(runtime, '_layout', lambda given: (paths, {'toolchain/python': executable}))
    builds = []
    def build(given, destination):
        builds.append(destination)
        destination.mkdir()
        (destination/'file').write_bytes((root/'node_dist/file').read_bytes())
    monkeypatch.setattr(runtime, '_build', build)
    return root, paths, builds


def invalid(call):
    with pytest.raises(runtime.EvaluationRuntimeError, match='^evaluation_runtime_invalid$') as caught:
        call()
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__


def test_prepare_private_receipt_and_verify_rebuilds_independently(layout, tmp_path):
    root, _, builds = layout
    output = tmp_path/'private'
    record = runtime.prepare_runtime(root, output=output)
    assert set(record) == runtime.FIELDS
    assert output.stat().st_mode & 0o777 == 0o700
    assert (output/'runtime.json').stat().st_mode & 0o777 == 0o600
    assert runtime.verify_runtime(root, output/'runtime.json') == record
    assert runtime.verify_runtime(root, deepcopy(record)) == record
    assert len(builds) == 3
    assert all(not path.parent.exists() for path in builds)


def test_prepare_refuses_existing_output_and_never_overwrites(layout, tmp_path):
    root, _, _ = layout
    output = tmp_path/'private'
    output.mkdir()
    marker = output/'sentinel'
    marker.write_bytes(b'preserve')
    invalid(lambda: runtime.prepare_runtime(root, output=output))
    assert marker.read_bytes() == b'preserve'


def test_forged_stale_dist_digest_cannot_replace_fresh_compilation(layout, tmp_path, monkeypatch):
    root, _, _ = layout
    record = runtime.prepare_runtime(root, output=tmp_path/'private')
    (root/'node_dist/file').write_bytes(b'stale')
    record['files']['node_dist/file'] = sha256(b'stale').hexdigest()
    record['identity_sha256'] = sha256(runtime._canonical({key: value for key, value in record.items()
        if key != 'identity_sha256'})).hexdigest()
    def fresh_build(given, destination):
        destination.mkdir()
        (destination/'file').write_bytes(b'fresh source output')
    monkeypatch.setattr(runtime, '_build', fresh_build)
    invalid(lambda: runtime.verify_runtime(root, record))


@pytest.mark.parametrize('mutation', ['extra', 'missing', 'changed'])
def test_complete_emitted_set_must_match_actual_build(layout, tmp_path, monkeypatch, mutation):
    root, _, _ = layout
    def build(given, destination):
        destination.mkdir()
        if mutation != 'missing':
            (destination/'file').write_bytes(b'changed' if mutation == 'changed' else b'node_dist')
        if mutation == 'extra':
            (destination/'extra').write_bytes(b'extra')
    monkeypatch.setattr(runtime, '_build', build)
    invalid(lambda: runtime.prepare_runtime(root, output=tmp_path/'private'))


@pytest.mark.parametrize('category', ['node_dependencies', 'python_dependencies', 'python_stdlib',
    'npm_toolchain', 'checkout_bytecode'])
def test_dependency_or_bytecode_drift_invalidates_identity(layout, tmp_path, category):
    root, _, _ = layout
    record = runtime.prepare_runtime(root, output=tmp_path/'private')
    filename = 'extra.pyc' if category == 'checkout_bytecode' else 'extra'
    (root/category/filename).write_bytes(b'new runtime bytes')
    invalid(lambda: runtime.verify_runtime(root, record))


def test_toolchain_tokenizer_and_candidate_drift_are_rechecked(layout, tmp_path, monkeypatch):
    root, _, _ = layout
    record = runtime.prepare_runtime(root, output=tmp_path/'private')
    (root/'python').write_bytes(b'changed binary')
    invalid(lambda: runtime.verify_runtime(root, record))
    (root/'python').write_bytes(b'synthetic executable')
    (root/'artifacts/tokenizers/cl100k_base.tiktoken').write_bytes(b'changed tokenizer')
    invalid(lambda: runtime.verify_runtime(root, record))
    monkeypatch.setattr(runtime, '_candidate', lambda given: (_ for _ in ()).throw(ValueError('private git output')))
    invalid(lambda: runtime.verify_runtime(root, record))


def test_escaping_symlink_fifo_and_cycle_are_refused(layout, tmp_path):
    root, _, _ = layout
    outside = tmp_path/'outside'
    outside.write_bytes(b'private')
    link = root/'node_dependencies/link'
    link.symlink_to(outside)
    invalid(lambda: runtime.prepare_runtime(root, output=tmp_path/'private'))
    link.unlink()
    os.mkfifo(link)
    invalid(lambda: runtime.prepare_runtime(root, output=tmp_path/'private'))
    link.unlink()
    link.symlink_to(root/'node_dependencies', target_is_directory=True)
    invalid(lambda: runtime.prepare_runtime(root, output=tmp_path/'private'))


def test_internal_file_symlink_is_recorded_by_complete_relative_path(layout, tmp_path):
    root, _, _ = layout
    (root/'node_dependencies/link').symlink_to(root/'node_dependencies/file')
    record = runtime.prepare_runtime(root, output=tmp_path/'private')
    assert record['files']['node_dependencies/link'] == record['files']['node_dependencies/file']


@pytest.mark.parametrize('field,value', [('revision', 'other'), ('source_commit', 'bad'),
    ('files', {'node_dist/../escape': 'd'*64}), ('runtime_versions', {'python': '3.14.6'}),
    ('extra', True), ('identity_sha256', '0'*64)])
def test_malformed_receipts_fail_before_build(layout, tmp_path, field, value):
    root, _, builds = layout
    record = runtime.prepare_runtime(root, output=tmp_path/'private')
    record[field] = value
    invalid(lambda: runtime.verify_runtime(root, record))
    assert len(builds) == 1


def test_private_receipt_permissions_and_symlink_are_required(layout, tmp_path):
    root, _, _ = layout
    output = tmp_path/'private'
    runtime.prepare_runtime(root, output=output)
    receipt = output/'runtime.json'
    receipt.chmod(0o644)
    invalid(lambda: runtime.verify_runtime(root, receipt))
    receipt.chmod(0o600)
    link = output/'link.json'
    link.symlink_to(receipt)
    invalid(lambda: runtime.verify_runtime(root, link))
    output.chmod(0o755)
    invalid(lambda: runtime.verify_runtime(root, receipt))


def test_inventory_caps_reject_before_large_reads(layout, tmp_path, monkeypatch):
    root, _, _ = layout
    monkeypatch.setattr(runtime, 'MAX_FILE_BYTES', 4)
    invalid(lambda: runtime.prepare_runtime(root, output=tmp_path/'private'))


def test_primary_source_gate_precedes_build_or_artifact_work(layout, tmp_path, monkeypatch):
    root, _, builds = layout
    monkeypatch.setattr(runtime, '_candidate', lambda given: (_ for _ in ()).throw(ValueError('private source')))
    invalid(lambda: runtime.prepare_runtime(root, output=tmp_path/'private'))
    assert builds == []
    assert not (tmp_path/'private').exists()


def test_source_gate_requires_python_no_bytecode_before_candidate_read(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'dont_write_bytecode', False)
    invalid(lambda: runtime.prepare_runtime(tmp_path, output=tmp_path/'private'))


def test_declared_runtime_versions_are_actual_commands_not_receipt_claims(tmp_path, monkeypatch):
    manifest = tmp_path/'packages/typescript/package.json'
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({'devDependencies': {'typescript': '7.0.2'}}))
    monkeypatch.setattr(sys, 'dont_write_bytecode', True)
    monkeypatch.setattr(runtime.shutil, 'which', lambda name: '/synthetic/'+name)
    responses = ['v26.5.0', '11.17.0', 'Version 7.0.2']
    commands = []
    def command(arguments):
        commands.append(arguments)
        return responses.pop(0)
    monkeypatch.setattr(runtime, '_command', command)
    configuration = {'supported_matrix': {'python': runtime.platform.python_version(),
        'node': '26.5.0', 'npm': '11.17.0', 'platform':sys.platform+'-'+runtime.platform.machine().lower()}}
    record = runtime._versions(tmp_path, configuration)
    assert record['typescript'] == '7.0.2'
    assert record['python_bytecode_writes'] is False
    assert len(commands) == 3
    responses[:] = ['v26.5.1', '11.17.0', 'Version 7.0.2']
    with pytest.raises(runtime.EvaluationRuntimeError):
        runtime._versions(tmp_path, configuration)
    responses[:] = ['v26.5.0', '11.17.0', 'Version 7.0.2']
    configuration['supported_matrix']['platform'] = 'unsupported-architecture'
    with pytest.raises(runtime.EvaluationRuntimeError):
        runtime._versions(tmp_path, configuration)


def test_dependency_mutation_during_build_fails_before_receipt(layout, tmp_path, monkeypatch):
    root, _, _ = layout
    original = runtime._build
    def build(given, destination):
        original(given, destination)
        (root/'python_dependencies/file').write_bytes(b'drift during compilation')
    monkeypatch.setattr(runtime, '_build', build)
    invalid(lambda: runtime.prepare_runtime(root, output=tmp_path/'private'))
    assert not (tmp_path/'private').exists()


def test_receipt_directory_and_byte_limits_are_enforced(layout, tmp_path, monkeypatch):
    root, _, _ = layout
    record = runtime.prepare_runtime(root, output=tmp_path/'private')
    monkeypatch.setattr(runtime, 'MAX_RECEIPT_BYTES', 100)
    invalid(lambda: runtime.verify_runtime(root, record))


def test_command_timeout_diagnostics_are_fixed(layout, tmp_path, monkeypatch):
    root, _, _ = layout
    import subprocess
    def build(given, destination):
        raise subprocess.TimeoutExpired('private command source', 120, output=b'private details')
    monkeypatch.setattr(runtime, '_build', build)
    invalid(lambda: runtime.prepare_runtime(root, output=tmp_path/'private'))


def test_stdlib_link_to_explicit_owned_toolchain_file_is_identified(layout, tmp_path):
    root, _, _ = layout
    (root/'python_stdlib/library').symlink_to(root/'python')
    record = runtime.prepare_runtime(root, output=tmp_path/'private')
    assert record['files']['python_stdlib/library'] == record['files']['toolchain/python']


def test_local_command_caps_output_and_timeout_without_retaining_processes():
    assert runtime._command([sys.executable, '-B', '-c', "print('synthetic version')"]) == 'synthetic version'
    with pytest.raises(runtime.EvaluationRuntimeError, match='^evaluation_runtime_invalid$'):
        runtime._command([sys.executable, '-B', '-c', "print('x'*5000)"])
    with pytest.raises((runtime.EvaluationRuntimeError, subprocess.TimeoutExpired)):
        runtime._command([sys.executable, '-B', '-c', 'import time; time.sleep(10)'], timeout=.02)



def test_empty_directory_entry_work_is_bounded(layout, tmp_path, monkeypatch):
    root, _, _ = layout
    for index in range(4):
        (root/'node_dependencies'/str(index)).mkdir()
    monkeypatch.setattr(runtime, 'MAX_ENTRIES', 3)
    invalid(lambda: runtime.prepare_runtime(root, output=tmp_path/'private'))



@pytest.mark.parametrize('forged', [False, True])
def test_existing_checkout_bytecode_is_refused_even_when_source_matches(layout, tmp_path, forged):
    import py_compile
    root, _, builds = layout
    source = root/'checkout_bytecode/helper.py'
    source.write_text('answer = 42\n')
    cached = root/'checkout_bytecode/helper.pyc'
    py_compile.compile(str(source), cfile=str(cached), doraise=True)
    if forged:
        cached.write_bytes(b'forged source cache')
    invalid(lambda: runtime.prepare_runtime(root, output=tmp_path/'private'))
    assert builds == []
    assert cached.exists()
    assert not (tmp_path/'private').exists()


def test_new_checkout_bytecode_invalidates_verification_without_removal(layout, tmp_path):
    root, _, _ = layout
    record = runtime.prepare_runtime(root, output=tmp_path/'private')
    cached = root/'checkout_bytecode/helper.pyc'
    cached.write_bytes(b'unverified executable cache')
    invalid(lambda: runtime.verify_runtime(root, record))
    assert cached.read_bytes() == b'unverified executable cache'


def test_layout_rejects_bytecode_in_every_owned_package_source_area(tmp_path, monkeypatch):
    packages = tmp_path/'packages'
    for name in ('python', 'typescript', 'mcp-python', 'mcp-typescript', 'langchain-python', 'langchain-typescript'):
        (packages/name/'src').mkdir(parents=True)
    monkeypatch.setattr(runtime, '_metadata', lambda root: tmp_path/'site-packages')
    monkeypatch.setattr(runtime.shutil, 'which', lambda name: str(tmp_path/'bin'/name))
    directories, _ = runtime._layout(tmp_path)
    assert 'checkout_bytecode/tools' in directories
    assert 'checkout_bytecode/evaluation/runners' in directories
    assert {key for key in directories if key.startswith('checkout_bytecode/packages/')} == {
        'checkout_bytecode/packages/'+name+'/src' for name in
        ('python', 'typescript', 'mcp-python', 'mcp-typescript', 'langchain-python', 'langchain-typescript')}


def test_cli_prepare_and_verify_dispatch_to_same_origin_api(layout, tmp_path, monkeypatch, capsys):
    root, _, _ = layout
    monkeypatch.setattr(runtime, 'ROOT', root)
    monkeypatch.setattr(sys, 'dont_write_bytecode', True)
    output = tmp_path/'private'
    assert runtime.main(['prepare', '--output', str(output)]) == 0
    prepared = json.loads(capsys.readouterr().out)
    assert prepared['state'] == 'prepared'
    assert set(prepared) == {'revision', 'state', 'identity_sha256', 'source_commit', 'files_count'}
    assert str(tmp_path) not in json.dumps(prepared)
    assert runtime.main(['verify', '--receipt', str(output/'runtime.json')]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified['state'] == 'verified'
    assert prepared['identity_sha256'] == verified['identity_sha256']


@pytest.mark.parametrize('arguments', [[], ['prepare'], ['verify'],
    ['prepare', '--output', 'private-source-text', '--root', 'credential-bearing-path'], ['unknown-private-value']])
def test_cli_invalid_arguments_emit_only_fixed_json(arguments, capsys):
    assert runtime.main(arguments) == 1
    captured = capsys.readouterr()
    assert captured.err == ''
    assert json.loads(captured.out) == {'revision': 'ECR-r1', 'state': 'failed',
        'error_code': 'evaluation_runtime_invalid'}


def test_cli_requires_no_bytecode_mode_before_dispatch(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'dont_write_bytecode', False)
    calls = []
    monkeypatch.setattr(runtime, 'prepare_runtime', lambda *args, **kwargs: calls.append(kwargs))
    assert runtime.main(['prepare', '--output', 'private-path']) == 1
    assert calls == []
    assert json.loads(capsys.readouterr().out)['error_code'] == 'evaluation_runtime_invalid'
