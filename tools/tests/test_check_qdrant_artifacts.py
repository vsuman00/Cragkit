"""Reject broken V5 archive and dependency identities before installation."""
import importlib.util
from pathlib import Path
import sys
import zipfile

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('check_qdrant_artifacts', TOOLS / 'check_qdrant_artifacts.py')
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def wheel(path, metadata):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('cragkit_mcp/__init__.py', '')
        archive.writestr('cragkit_mcp/py.typed', '')
        archive.writestr('cragkit_mcp-1.0.0rc1.dist-info/METADATA', metadata)


def test_mcp_metadata_rejects_core_registry_version_drift(tmp_path):
    artifact = tmp_path / 'mcp.whl'
    metadata = 'Name: cragkit-mcp\nVersion: 1.0.0rc1\nRequires-Dist: cragkit==1.0.0rc1\nRequires-Dist: mcp==2.3.0\n'
    wheel(artifact, metadata)
    assert 'cragkit_mcp/py.typed' in module.inspect_mcp_wheel(artifact)
    wheel(artifact, metadata.replace('mcp==2.3.0', 'mcp>=2.3.0'))
    with pytest.raises(module.require.__globals__['ArtifactError'], match='mcp_dependencies'):
        module.inspect_mcp_wheel(artifact)


def test_mcp_artifact_cannot_relabel_prototype_metadata_as_rc(tmp_path):
    artifact = tmp_path / 'mcp.whl'
    wheel(artifact, 'Name: cragkit-mcp\nVersion: 0.0.0\n'
        'Requires-Dist: cragkit==1.0.0rc1\nRequires-Dist: mcp==2.3.0\n')
    with pytest.raises(module.require.__globals__['ArtifactError'], match='mcp_identity'):
        module.inspect_mcp_wheel(artifact)


@pytest.mark.parametrize('actual', [{'version': '2', 'integrity': 'sha512-reviewed'},
                                    {'version': '1', 'integrity': 'sha512-other'},
                                    {'version': '1'}])
def test_lock_rejects_version_or_integrity_drift(actual):
    expected = {'node_modules/sdk': {'version': '1', 'integrity': 'sha512-reviewed'}}
    with pytest.raises(module.require.__globals__['ArtifactError'], match='v5_node_lock_drift'):
        module.check_node_lock({'node_modules/sdk': actual}, expected)


def test_lock_rejects_unreviewed_transitive_package():
    with pytest.raises(module.require.__globals__['ArtifactError'], match='v5_node_lock_drift'):
        module.check_node_lock({'node_modules/unreviewed': {'version': '1', 'integrity': 'sha512-x'}}, {})


def test_lock_accepts_reviewed_transitives_and_local_archives():
    expected = {'node_modules/sdk': {'version': '1', 'integrity': 'sha512-reviewed'}}
    module.check_node_lock({**expected, 'node_modules/cragkit': {'version': '1.0.0-rc.1'}}, expected)


def test_existing_output_is_preserved(tmp_path):
    report = tmp_path / 'acceptance.json'
    report.write_text('existing evidence')
    with pytest.raises(module.require.__globals__['ArtifactError'], match='v5_output_not_empty'):
        module.accept(tmp_path, tmp_path, tmp_path)
    assert report.read_text() == 'existing evidence'
