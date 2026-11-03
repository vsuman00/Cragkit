import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SPEC = importlib.util.spec_from_file_location('check_artifacts', Path(__file__).resolve().parents[1] / 'check_artifacts.py')
assert SPEC and SPEC.loader
ART = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ART)


@pytest.mark.parametrize('name', ['../secret', '/absolute', 'package/../../secret', 'package/.env',
                                 'package/node_modules/x', 'package/models/weights', 'C:/secret',
                                 'package\\secret', 'package/cache.gguf', 'package/__pycache__/x.pyc',
                                 'package/.pgpass', 'package/pgpass', 'package/pgpass.conf',
                                 'package/.pg_service.conf', 'package/client.p12', 'package/client.pfx'])
def test_archive_names_reject_escapes_secrets_and_heavy_assets(name):
    with pytest.raises(ART.ArtifactError):
        ART.safe_member(name)


def tar(path, files):
    with tarfile.open(path, 'w:gz') as archive:
        for name, content in files.items():
            item = tarfile.TarInfo(name)
            item.size = len(content)
            archive.addfile(item, io.BytesIO(content))


def test_tar_links_are_not_accepted(tmp_path):
    path = tmp_path / 'bad.tar.gz'
    with tarfile.open(path, 'w:gz') as archive:
        item = tarfile.TarInfo('package/link')
        item.type = tarfile.SYMTYPE
        item.linkname = '/private'
        archive.addfile(item)
    with pytest.raises(ART.ArtifactError, match='archive_special_member'):
        ART.archive_files(path)


def test_wheel_requires_typed_core_and_only_declared_core_dependency(tmp_path):
    path = tmp_path / 'test.whl'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('cragkit/__init__.py', '')
    with pytest.raises(ART.ArtifactError, match='wheel_missing_core'):
        ART.inspect_wheel(path)


def test_npm_export_must_exist_in_archive(tmp_path):
    path = tmp_path / 'test.tgz'
    package = {'name': 'cragkit', 'version': '1.0.0-rc.1', 'private': True, 'dependencies': {'zod': '4.6.7'},
               'exports': {name: {'import': f'./dist/{stem}.js', 'types': f'./dist/{stem}.d.ts'}
                           for name, stem in [('.', 'index'), ('./contracts', 'contracts'), ('./errors', 'errors'), ('./postgres', 'postgres'), ('./embeddings', 'embeddings')]}}
    tar(path, {'package/package.json': json.dumps(package).encode(), 'package/dist/index.js': b''})
    with pytest.raises(ART.ArtifactError, match='npm_missing_export'):
        ART.inspect_npm(path)


def test_prototype_npm_identity_is_refused_before_export_checks(tmp_path):
    path = tmp_path / 'prototype.tgz'
    tar(path, {'package/package.json':json.dumps({
        'name':'cragkit', 'version':'0.0.0', 'private':True,
        'dependencies':{'zod':'4.6.7'}, 'exports':{},
    }).encode()})
    with pytest.raises(ART.ArtifactError, match='npm_identity'):
        ART.inspect_npm(path)


def test_subprocess_failures_are_bounded_and_do_not_record_captured_secrets(tmp_path, monkeypatch):
    seen = []
    def fail(command, **kwargs):
        seen.append(kwargs)
        return subprocess.CompletedProcess(command, 2, stdout='private-token', stderr='private-provider')
    monkeypatch.setattr(ART.subprocess, 'run', fail)
    commands = []
    with pytest.raises(ART.ArtifactError, match='command_failed'):
        ART.run(['fake', 'path with spaces'], tmp_path, commands)
    assert seen[0]['timeout'] == 120
    assert commands[0]['returncode'] == 2
    recorded = json.dumps(commands)
    assert 'private-token' not in recorded
    assert 'private-provider' not in recorded


def test_failed_build_cleans_temporary_workspace_and_records_failure(tmp_path, monkeypatch):
    temporary = tmp_path / 'owned'
    class Temporary:
        def __init__(self, **kwargs): pass
        def __enter__(self): temporary.mkdir(); return str(temporary)
        def __exit__(self, *args): temporary.rmdir()
    def fail(*args, **kwargs): raise ART.ArtifactError('fake_build_failure')
    monkeypatch.setattr(ART.tempfile, 'TemporaryDirectory', Temporary)
    monkeypatch.setattr(ART, 'run', fail)
    output = tmp_path / 'output with spaces'
    with pytest.raises(ART.ArtifactError, match='fake_build_failure'):
        ART.accept_artifacts(tmp_path, output)
    assert not temporary.exists()
    report = json.loads((output / 'acceptance.json').read_text())
    assert report['state'] == 'failed'
    assert report['temporary_environments_cleaned'] is True
    assert report['imports'] == {}


def test_installed_import_guards_require_optional_vector_api():
    assert 'PostgresVectorIndexer' in ART.PYTHON_PROBE
    assert 'VectorIngestionReceipt' in ART.PYTHON_PROBE
    assert 'postgres.PostgresVectorIndexer' in ART.NODE_PROBE


def test_native_harness_links_only_data_and_installed_product(tmp_path):
    root, work, node = tmp_path / 'checkout', tmp_path / 'work', tmp_path / 'node'
    (root / 'tools/__pycache__').mkdir(parents=True)
    (root / 'tools/check_python_postgres.py').write_text('pass\n')
    (root / 'tools/__pycache__/private.pyc').write_bytes(b'not copied')
    for name in ('storage', 'evaluation', 'contracts', 'artifacts/tokenizers'):
        (root / name).mkdir(parents=True)
    (node / 'node_modules/cragkit/dist').mkdir(parents=True)
    work.mkdir()
    python = work / 'wheel/bin/python'
    config = tmp_path / 'private-config.json'
    command, harness, environment = ART.native_harness(root, work, python, node, config)
    assert command[:4] == [str(python), '-I', '-B', '-c']
    assert command[5:7] == [str(harness / 'tools'), str(harness / 'tools/check_python_postgres.py')]
    assert command[-5:] == ['--allow-test-writes', '--neon', '--hybrid', '--evidence', '--typescript']
    assert environment == dict(CRAGKIT_REQUIRE_INSTALLED_PREFIX=str(work / 'wheel'),
                               CRAGKIT_INSTALLED_NODE_ROOT=str(node / 'node_modules/cragkit'))
    assert (harness / 'tools/check_python_postgres.py').is_file()
    assert not (harness / 'tools/__pycache__').exists()
    assert not (harness / 'packages/python').exists()
    assert not (harness / 'packages/typescript/src').exists()
    assert (harness / 'packages/typescript/dist').resolve() == (node / 'node_modules/cragkit/dist').resolve()
    assert (harness / 'packages/typescript/node_modules').resolve() == (node / 'node_modules').resolve()
    assert (harness / 'contracts').resolve() == (root / 'contracts').resolve()
    assert 'PYTHONPATH' not in environment


def installed_probe_setup(tmp_path):
    root, work, node = tmp_path / 'checkout', tmp_path / 'work', tmp_path / 'node'
    for directory in [root / 'tools', root / 'examples', root / 'contracts/fixtures', work, node]:
        directory.mkdir(parents=True)
    for name in ['tools/probe_installed_evidence.py', 'tools/probe_installed_evidence.mjs',
                 'examples/evidence.py', 'examples/evidence.mjs']:
        (root / name).write_text('copied outside checkout')
    for filename in ['retrieval.json', 'context.json', 'packing.json', 'assessment.json', 'evidence-pipeline.json']:
        (root / 'contracts/fixtures' / filename).write_text(json.dumps(dict(source_cases=[{}], cases=[{}], token_cases=[{}])))
    result = dict(revision='INST-r1', source_cases=[{'state': 'verified'}],
        context=dict(cases=[{'context': '[]'}], token_counts=[{'id': 'regression', 'tokens': 4}]),
        packing=[{'aliases': {'id': ['seed']}}], assessment=[{'status': 'partial'}], pipeline=[{'rebalance_count': 1}])
    examples = dict(partial=dict(status='partial'), strict_budget=dict(counting_mode='strict'))
    return root, work, node, result, examples


def test_installed_probe_compares_complete_outputs_and_explicit_paths(tmp_path, monkeypatch):
    root, work, node, result, examples = installed_probe_setup(tmp_path)
    seen = []
    def fake_run(command, cwd, commands, **kwargs):
        seen.append((command, cwd))
        return json.dumps(result if any('probe_installed_evidence' in arg for arg in command) else examples)
    monkeypatch.setattr(ART, 'run', fake_run)
    report = ART.installed_evidence(root, work, work / 'wheel/bin/python', node, [])
    assert report['state'] == 'passed' and report['results'] == result and report['examples'] == examples
    assert report['counts'] == dict(source_cases=1, context_cases=1, token_cases=1, packing_cases=1, assessment_cases=1, pipeline_cases=1)
    assert len(seen) == 4
    assert seen[0][0][1:3] == ['-I', '-B']
    assert '--fixtures' in seen[0][0] and '--tokenizer' in seen[0][0] and '--prefix' in seen[0][0]
    assert str(work / 'wheel') in seen[0][0]
    assert str(node / 'node_modules/cragkit') in seen[1][0]
    assert all(cwd in (work, node) for _, cwd in seen)


def test_installed_probe_rejects_equal_counts_with_different_nested_results(tmp_path, monkeypatch):
    root, work, node, result, examples = installed_probe_setup(tmp_path)
    def fake_run(command, cwd, commands, **kwargs):
        value = json.loads(json.dumps(result))
        if command[0] == 'node': value['context']['token_counts'][0]['tokens'] = 2
        return json.dumps(value)
    monkeypatch.setattr(ART, 'run', fake_run)
    with pytest.raises(ART.ArtifactError, match='installed_evidence_parity'):
        ART.installed_evidence(root, work, work / 'wheel/bin/python', node, [])


@pytest.mark.parametrize('flags', [['--evidence-native'], ['--neon'],
    ['--postgres-config', '/private/config', '--evidence-native'],
    ['--postgres-config', '/private/config', '--allow-test-writes', '--evidence-native']])
def test_hosted_flags_require_explicit_target_and_write_consent(flags, monkeypatch):
    monkeypatch.setattr(ART.sys, 'argv', ['check_artifacts.py', *flags])
    monkeypatch.setattr(ART, 'accept_artifacts', lambda *args, **kwargs: pytest.fail('must reject before build'))
    with pytest.raises(SystemExit) as caught: ART.main()
    assert caught.value.code == 2


def test_legacy_main_call_shape_is_preserved(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ART.sys, 'argv', ['check_artifacts.py', '--output-dir', str(tmp_path)])
    def accept(root, output, config):
        calls.append((root, output, config))
        return dict(state='passed', artifacts={}, imports={})
    monkeypatch.setattr(ART, 'accept_artifacts', accept)
    assert ART.main() == 0
    assert calls == [(ART.ROOT, tmp_path, None)]


def test_native_options_reject_without_building(tmp_path):
    with pytest.raises(ART.ArtifactError, match='native_evidence_requires_neon_config'):
        ART.accept_artifacts(tmp_path, tmp_path / 'out', evidence_native=True)
