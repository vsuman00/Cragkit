"""Preparation failures and ownership rules; native acceptance is a separate run."""
import json
from hashlib import sha256
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import postgres_vector_fixture as module


def layout(tmp_path, monkeypatch):
    global_root=tmp_path/'global'
    paths={name:global_root/relative for name,relative in
           [('bindir','Cellar/postgresql@17/17.11/bin'),('sharedir','share/postgresql@17'),('pkglibdir','lib/postgresql@17')]}
    for p in paths.values():p.mkdir(parents=True)
    (paths['bindir']/'pg_config').write_text('binary')
    (paths['sharedir']/'extension').mkdir()
    (paths['sharedir']/'extension/vector.control').write_text('GLOBAL 0.8.7')
    (paths['pkglibdir']/'vector.so').write_bytes(b'GLOBAL 0.8.7')
    source=tmp_path/'source';source.mkdir();(source/'sql').mkdir()
    (source/'vector.control').write_text("default_version = '0.8.0'\n")
    (source/'vector.so').write_bytes(b'BUILT 0.8.0')
    (source/'sql/vector--0.8.0.sql').write_text('genuine source script')
    destination=tmp_path/'private'
    def output(args):
        if args[0]=='git':return module.VECTOR_COMMIT
        if args[-1]=='--version':return 'PostgreSQL 17.11 (Homebrew)'
        name=args[-1][2:]
        if Path(args[0]).is_relative_to(destination):return str(destination/paths[name].relative_to(global_root))
        return str(paths[name])
    monkeypatch.setattr(module,'_output',output)
    return paths,source,destination


def test_preparation_preserves_global_files_and_records_real_outputs(tmp_path,monkeypatch):
    paths,source,destination=layout(tmp_path,monkeypatch)
    result=module.prepare_private_postgres(paths['bindir'],source,destination)
    manifest=json.loads((destination/'preparation.json').read_text())
    assert result.is_relative_to(destination)
    assert manifest['source_commit']==module.VECTOR_COMMIT
    assert manifest['binary_sha256']==sha256(b'BUILT 0.8.0').hexdigest()
    assert (paths['pkglibdir']/'vector.so').read_bytes()==b'GLOBAL 0.8.7'
    assert (paths['sharedir']/'extension/vector.control').read_text()=='GLOBAL 0.8.7'
    with pytest.raises(FileExistsError):module.prepare_private_postgres(paths['bindir'],source,destination)


def test_wrong_source_version_fails_before_copy(tmp_path,monkeypatch):
    paths,source,destination=layout(tmp_path,monkeypatch)
    (source/'vector.control').write_text("default_version = '0.8.7'")
    with pytest.raises(RuntimeError,match='control_version'):
        module.prepare_private_postgres(paths['bindir'],source,destination)
    assert not destination.exists()


def test_unbuilt_source_cannot_masquerade_as_supported_extension(tmp_path,monkeypatch):
    paths,source,destination=layout(tmp_path,monkeypatch)
    (source/'vector.so').unlink()
    with pytest.raises(RuntimeError,match='build_missing'):
        module.prepare_private_postgres(paths['bindir'],source,destination)
    assert not destination.exists()


def test_relocation_escape_removes_only_owned_copy(tmp_path,monkeypatch):
    paths,source,destination=layout(tmp_path,monkeypatch)
    original=module._output
    def escaped(args):
        if args[0]!='git' and Path(args[0]).is_relative_to(destination) and args[-1]=='--sharedir':
            return str(paths['sharedir'])
        return original(args)
    monkeypatch.setattr(module,'_output',escaped)
    with pytest.raises(RuntimeError,match='relocation_escape'):
        module.prepare_private_postgres(paths['bindir'],source,destination)
    assert not destination.exists()
    assert (paths['sharedir']/'extension/vector.control').read_text()=='GLOBAL 0.8.7'


def test_unproven_prefix_refused_before_server_creation(tmp_path,monkeypatch):
    paths,source,destination=layout(tmp_path,monkeypatch)
    with pytest.raises(RuntimeError,match='preparation_required'):
        module.V6PostgresFixture(paths['bindir'],tmp_path/'artifacts')


def test_binary_changed_after_preparation_is_refused(tmp_path,monkeypatch):
    paths,source,destination=layout(tmp_path,monkeypatch)
    binary=module.prepare_private_postgres(paths['bindir'],source,destination)
    (destination/'lib/postgresql@17/vector.so').write_bytes(b'DRIFT')
    with pytest.raises(RuntimeError,match='binary_drift'):
        module.V6PostgresFixture(binary,tmp_path/'artifacts')


def test_extension_control_drift_refused_before_start(tmp_path,monkeypatch):
    paths,source,destination=layout(tmp_path,monkeypatch)
    binary=module.prepare_private_postgres(paths['bindir'],source,destination)
    (destination/'share/postgresql@17/extension/vector.control').write_text("default_version = '0.8.7'")
    with pytest.raises(RuntimeError,match='metadata_drift'):
        module.V6PostgresFixture(binary,tmp_path/'artifacts')
