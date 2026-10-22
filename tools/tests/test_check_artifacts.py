import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import zipfile

import pytest

SPEC = importlib.util.spec_from_file_location('check_artifacts', Path(__file__).resolve().parents[1] / 'check_artifacts.py')
assert SPEC and SPEC.loader
ART = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ART)


@pytest.mark.parametrize('name', ['../secret', '/absolute', 'package/../../secret', 'package/.env',
                                 'package/node_modules/x', 'package/models/weights', 'C:/secret',
                                 'package\\secret', 'package/cache.gguf', 'package/__pycache__/x.pyc'])
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
    package = {'name': 'cragkit', 'version': '0.0.0', 'private': True, 'dependencies': {'zod': '4.6.7'},
               'exports': {name: {'import': f'./dist/{stem}.js', 'types': f'./dist/{stem}.d.ts'}
                           for name, stem in [('.', 'index'), ('./contracts', 'contracts'), ('./errors', 'errors'), ('./postgres', 'postgres'), ('./embeddings', 'embeddings')]}}
    tar(path, {'package/package.json': json.dumps(package).encode(), 'package/dist/index.js': b''})
    with pytest.raises(ART.ArtifactError, match='npm_missing_export'):
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
