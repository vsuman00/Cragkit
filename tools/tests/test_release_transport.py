"""Fixed release transport tests use synthetic candidates and no live services."""
from contextlib import nullcontext
import io
import json
import os
from pathlib import Path
import stat
import struct
import socket
import subprocess
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import release_transport as T
import prepare_release_products as P
from test_check_ci_bundle import bundle
from test_prepare_release_products import candidate


@pytest.fixture
def transport(candidate, tmp_path, monkeypatch):
    inputs, *_ = candidate
    products, manifest = P.expected_products(**inputs)
    raw = products[P.MANIFEST_NAME]
    monkeypatch.setattr(T, 'MANIFEST_SHA256', P.digest(raw))
    path = tmp_path / 'reviewed-manifest.json'
    path.write_bytes(raw)
    return dict(**inputs, manifest=path), products, manifest


def packed(transport, tmp_path):
    inputs, products, manifest = transport
    output = tmp_path / 'packed'
    receipt = T.pack_transport(**inputs, output=output)
    raw = (output / T.TRANSPORT_NAME).read_bytes()
    return raw, receipt, products, manifest


def unpack(raw, tmp_path, name='unpacked', expected_sha256=None):
    archive = tmp_path / 'transport.zip'
    archive.write_bytes(raw)
    output = tmp_path / name
    result = T.unpack_transport(archive=archive, output=output,
        expected_sha256=expected_sha256 if expected_sha256 is not None else P.digest(raw))
    return output, result


def rewritten(raw, change):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = [(item, archive.read(item)) for item in archive.infolist()]
    entries = change(entries)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for item, content in entries:
            archive.writestr(item, content)
    return stream.getvalue()


def test_round_trip_revalidates_nine_products_and_retains_exact_candidate(transport, tmp_path):
    raw, receipt, products, manifest = packed(transport, tmp_path)
    output, result = unpack(raw, tmp_path)
    assert receipt['revision'] == result['revision'] == 'PWK-r1'
    assert receipt['state'] == 'prepared_local' and result['state'] == 'verified_local'
    assert receipt['published'] is receipt['publication_authorized'] is False
    assert result['published'] is result['publication_authorized'] is False
    assert receipt['transport'] == dict(path=T.TRANSPORT_NAME, sha256=P.digest(raw), bytes=len(raw))
    assert len(receipt['members']) == 5
    assert receipt['manifest_sha256'] == P.digest(products[P.MANIFEST_NAME])
    for name, content in products.items():
        assert (output / name).read_bytes() == content
    inputs, *_ = transport
    restored = {key: output / 'candidate' / name for key, name in T.INPUT_NAMES.items()}
    for key, path in restored.items():
        assert path.read_bytes() == inputs[key].read_bytes()
    rebuilt, rebuilt_manifest = P.expected_products(**restored)
    assert rebuilt == products and rebuilt_manifest == manifest
    assert len(list(output.rglob('*'))) == 18  # 14 files, four fixed directories
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert set(archive.namelist()) == set(T.MEMBER_LIMITS)
        for item in archive.infolist():
            assert stat.S_IFMT(item.external_attr >> 16) == stat.S_IFREG
            assert stat.S_IMODE(item.external_attr >> 16) == 0o600
    for root in (tmp_path / 'packed', output):
        for path in (root, *root.rglob('*')):
            assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)


def test_transport_and_receipt_are_deterministic(transport, tmp_path):
    inputs, *_ = transport
    first, second = tmp_path / 'first', tmp_path / 'second'
    assert T.pack_transport(**inputs, output=first) == T.pack_transport(**inputs, output=second)
    assert (first / T.TRANSPORT_NAME).read_bytes() == (second / T.TRANSPORT_NAME).read_bytes()
    assert (first / T.RECEIPT_NAME).read_bytes() == (second / T.RECEIPT_NAME).read_bytes()


def test_transport_has_no_network_or_subprocess_dependency(transport, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('offline transport attempted network or process execution')
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(os, 'system', forbidden)
    raw, *_ = packed(transport, tmp_path)
    output, _ = unpack(raw, tmp_path)
    assert (output / P.MANIFEST_NAME).is_file()


def test_pack_validates_captured_bytes_after_input_path_is_replaced(transport, tmp_path, monkeypatch):
    inputs, *_ = transport
    candidate_bytes = inputs['archive'].read_bytes()
    original = P.read_file
    def replace_after_read(path, limit):
        raw = original(path, limit)
        if path == inputs['archive']:
            path.write_bytes(b'replacement')
        return raw
    monkeypatch.setattr(P, 'read_file', replace_after_read)
    raw, *_ = packed(transport, tmp_path)
    output, _ = unpack(raw, tmp_path)
    assert (output / 'candidate' / T.INPUT_NAMES['archive']).read_bytes() == candidate_bytes
    assert inputs['archive'].read_bytes() == b'replacement'


@pytest.mark.parametrize('raw', [b'{"id":1,"id":1}', b'{"value":NaN}',
                                b'{"value":Infinity}', b'{"value":1e999}',
                                b'{"private-token":', b'\xff'])
def test_malformed_metadata_has_fixed_safe_diagnostics(transport, tmp_path, raw):
    inputs, *_ = transport
    inputs['run'].write_bytes(raw)
    with pytest.raises(T.TransportError) as error:
        T.pack_transport(**inputs, output=tmp_path / 'failed')
    assert str(error.value) == 'transport_invalid'
    assert error.value.__context__ is None
    assert not (tmp_path / 'failed').exists()


@pytest.mark.parametrize('change', ['manifest', 'regenerated_manifest', 'source', 'run',
                                   'jobs', 'artifact', 'bundle'])
def test_pack_checks_pinned_manifest_and_full_ci_identity(transport, tmp_path, monkeypatch, change):
    inputs, *_ = transport
    if change == 'manifest':
        inputs['manifest'].write_bytes(b'{"published":true}')
    elif change == 'regenerated_manifest':
        inputs['manifest'].write_bytes(inputs['manifest'].read_bytes() + b' ')
        monkeypatch.setattr(T, 'MANIFEST_SHA256', P.digest(inputs['manifest'].read_bytes()))
    elif change == 'bundle':
        inputs['archive'].write_bytes(inputs['archive'].read_bytes() + b'changed')
    else:
        key = 'run' if change == 'source' else change
        value = json.loads(inputs[key].read_bytes())
        if change == 'source': value['head_sha'] = 'b' * 40
        elif key == 'jobs': value['jobs'][0]['id'] = 999
        else: value['id'] = 999
        inputs[key].write_text(json.dumps(value))
    with pytest.raises(T.TransportError) as error:
        T.pack_transport(**inputs, output=tmp_path / 'failed')
    assert error.value.__context__ is None
    assert not (tmp_path / 'failed').exists()


@pytest.mark.parametrize('key', ['archive', 'run', 'jobs', 'artifact', 'manifest'])
def test_pack_refuses_linked_source_files(transport, tmp_path, key):
    inputs, *_ = transport
    linked = tmp_path / 'linked'
    linked.symlink_to(inputs[key])
    inputs[key] = linked
    with pytest.raises(T.TransportError):
        T.pack_transport(**inputs, output=tmp_path / 'failed')
    assert not (tmp_path / 'failed').exists()


@pytest.mark.parametrize('value', ['', 'a' * 63, 'A' * 64, 'z' * 64, '0' * 64, None])
def test_unpack_requires_independent_exact_digest(transport, tmp_path, value):
    raw, *_ = packed(transport, tmp_path)
    archive = tmp_path / 'transport.zip'
    archive.write_bytes(raw)
    with pytest.raises(T.TransportError):
        T.unpack_transport(archive=archive, expected_sha256=value, output=tmp_path / 'failed')
    assert not (tmp_path / 'failed').exists()


@pytest.mark.parametrize('change', ['missing', 'extra', 'duplicate', 'traversal', 'absolute',
                                   'backslash', 'symlink', 'directory', 'fifo', 'permission',
                                   'compression', 'comment', 'extra_field', 'timestamp',
                                   'encrypted', 'manifest', 'candidate', 'metadata', 'trailer'])
def test_untrusted_transport_is_rejected_before_output(transport, tmp_path, change):
    raw, *_ = packed(transport, tmp_path)
    def alter(entries):
        item, content = entries[0]
        if change == 'missing': return entries[1:]
        if change == 'extra': return entries + [(zipfile.ZipInfo('extra'), b'x')]
        if change == 'duplicate': return entries[:-1] + [entries[0]]
        if change in ('traversal', 'absolute', 'backslash'):
            item.filename = {'traversal': '../outside', 'absolute': '/outside',
                             'backslash': 'candidate\\outside'}[change]
        elif change == 'symlink': item.external_attr = (stat.S_IFLNK | 0o600) << 16
        elif change == 'directory': item.external_attr = (stat.S_IFDIR | 0o600) << 16
        elif change == 'fifo': item.external_attr = (stat.S_IFIFO | 0o600) << 16
        elif change == 'permission': item.external_attr = (stat.S_IFREG | 0o644) << 16
        elif change == 'compression': item.compress_type = zipfile.ZIP_DEFLATED
        elif change == 'comment': item.comment = b'private-token'
        elif change == 'extra_field': item.extra = b'\xff\xff\x00\x00'
        elif change == 'timestamp': item.date_time = (2020, 1, 1, 0, 0, 0)
        elif change in ('manifest', 'candidate', 'metadata'):
            target = {'manifest': P.MANIFEST_NAME, 'candidate': T.INPUT_NAMES['archive'],
                      'metadata': T.INPUT_NAMES['run']}[change]
            return [(header, data + b'private-token' if header.filename == target else data)
                    for header, data in entries]
        return [(item, content), *entries[1:]]
    if change == 'trailer': raw += b'private-token'
    elif change == 'encrypted':
        # writestr clears flag_bits; set both local and central bits afterward.
        modified = bytearray(raw)
        struct.pack_into('<H', modified, 6, 1)
        central = modified.index(b'PK\x01\x02')
        struct.pack_into('<H', modified, central + 8, 1)
        raw = bytes(modified)
    else:
        with pytest.warns(UserWarning) if change == 'duplicate' else nullcontext():
            raw = rewritten(raw, alter)
    with pytest.raises(T.TransportError) as error:
        unpack(raw, tmp_path, name='failed')
    assert 'private-token' not in str(error.value)
    assert error.value.__context__ is None
    assert not (tmp_path / 'failed').exists()
    assert not (tmp_path.parent / 'outside').exists()


@pytest.mark.parametrize('change', ['raw', 'member', 'expanded', 'central', 'many_entries'])
def test_raw_expanded_member_and_parser_allocation_bounds(transport, tmp_path, monkeypatch, change):
    raw, *_ = packed(transport, tmp_path)
    if change == 'raw': monkeypatch.setattr(T, 'MAX_TRANSPORT', len(raw) - 1)
    elif change == 'expanded': monkeypatch.setattr(T, 'MAX_EXPANDED', 1)
    elif change == 'member':
        monkeypatch.setitem(T.MEMBER_LIMITS, T.INPUT_NAMES['archive'], 1)
    else:
        modified = bytearray(raw)
        if change == 'central': struct.pack_into('<L', modified, len(raw) - 10, 0x7fffffff)
        else: struct.pack_into('<H', modified, len(raw) - 12, 65535)
        raw = bytes(modified)
        def never_parse(*args, **kwargs):
            pytest.fail('ZIP parser called before central-directory preflight')
        monkeypatch.setattr(T.zipfile, 'ZipFile', never_parse)
    with pytest.raises(T.TransportError):
        unpack(raw, tmp_path, name='failed')
    assert not (tmp_path / 'failed').exists()


@pytest.mark.parametrize('mode', ['pack', 'unpack'])
@pytest.mark.parametrize('existing', ['file', 'directory', 'symlink', 'broken_symlink'])
def test_existing_output_is_preserved(transport, tmp_path, mode, existing):
    raw, *_ = packed(transport, tmp_path)
    output = tmp_path / 'existing'
    if existing == 'file': output.write_bytes(b'keep')
    elif existing == 'directory':
        output.mkdir()
        (output / 'keep').write_bytes(b'keep')
    else: output.symlink_to(tmp_path / ('packed' if existing == 'symlink' else 'missing'))
    inputs, *_ = transport
    with pytest.raises(T.TransportError, match='output_exists'):
        if mode == 'pack': T.pack_transport(**inputs, output=output)
        else:
            archive = tmp_path / 'transport.zip'
            archive.write_bytes(raw)
            T.unpack_transport(archive=archive, expected_sha256=P.digest(raw), output=output)
    assert os.path.lexists(output)
    if existing == 'file': assert output.read_bytes() == b'keep'
    if existing == 'directory': assert (output / 'keep').read_bytes() == b'keep'


@pytest.mark.parametrize('mode', ['pack', 'unpack'])
def test_concurrent_destination_claim_preserves_foreign_directory(transport, tmp_path, monkeypatch, mode):
    raw, *_ = packed(transport, tmp_path)
    output = tmp_path / 'raced'
    original = Path.mkdir
    def race(path, *args, **kwargs):
        if path == output:
            original(path)
            (path / 'foreign').write_bytes(b'keep')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'mkdir', race)
    inputs, *_ = transport
    with pytest.raises(T.TransportError):
        if mode == 'pack': T.pack_transport(**inputs, output=output)
        else:
            archive = tmp_path / 'transport.zip'
            archive.write_bytes(raw)
            T.unpack_transport(archive=archive, expected_sha256=P.digest(raw), output=output)
    assert sorted(path.name for path in output.iterdir()) == ['foreign']
    assert (output / 'foreign').read_bytes() == b'keep'
    assert not list(tmp_path.glob('.cragkit-transport-*'))


@pytest.mark.parametrize('mode', ['pack', 'unpack'])
def test_failed_exposure_preserves_foreign_files_and_has_no_completion_marker(transport, tmp_path,
                                                                          monkeypatch, mode):
    raw, *_ = packed(transport, tmp_path)
    output = tmp_path / 'failed'
    original = P.os.link
    calls = 0
    def fail(source, target, **kwargs):
        nonlocal calls
        calls += 1
        assert not (output / (T.RECEIPT_NAME if mode == 'pack' else P.MANIFEST_NAME)).exists()
        if calls == 2:
            (output / 'foreign').write_bytes(b'keep')
            raise OSError('private-token')
        return original(source, target, **kwargs)
    monkeypatch.setattr(P.os, 'link', fail)
    inputs, *_ = transport
    with pytest.raises(T.TransportError) as error:
        if mode == 'pack': T.pack_transport(**inputs, output=output)
        else:
            archive = tmp_path / 'transport.zip'
            archive.write_bytes(raw)
            T.unpack_transport(archive=archive, expected_sha256=P.digest(raw), output=output)
    assert str(error.value) == 'transport_invalid' and error.value.__context__ is None
    assert (output / 'foreign').read_bytes() == b'keep'
    assert sorted(path.name for path in output.iterdir()) == ['foreign']
    assert not list(tmp_path.glob('.cragkit-transport-*'))


def test_cli_redacts_payload_errors_and_does_not_create_output(tmp_path, capsys):
    output = tmp_path / 'failed'
    assert T.main(['unpack', '--archive', str(tmp_path / 'private-token'),
                   '--expected-sha256', '0' * 64, '--output', str(output)]) == 1
    message = capsys.readouterr().out
    assert 'private-token' not in message
    result = json.loads(message)
    assert result['state'] == 'failed'
    assert result['published'] is result['publication_authorized'] is False
    assert not output.exists()


def test_failure_cleanup_preserves_foreign_replacement_inode(transport, tmp_path, monkeypatch):
    inputs, *_ = transport
    output = tmp_path / 'failed'
    original = P.os.link
    first = None
    def replace_then_fail(source, target, **kwargs):
        nonlocal first
        if first is None:
            original(source, target, **kwargs)
            first = target
            return
        first.unlink()
        first.write_bytes(b'foreign replacement')
        raise OSError('private-token')
    monkeypatch.setattr(P.os, 'link', replace_then_fail)
    with pytest.raises(T.TransportError):
        T.pack_transport(**inputs, output=output)
    assert first.read_bytes() == b'foreign replacement'
    assert sorted(path.name for path in output.iterdir()) == [T.TRANSPORT_NAME]
    assert not (output / T.RECEIPT_NAME).exists()


@pytest.mark.parametrize('mode', ['pack', 'unpack'])
def test_symlinked_output_parent_is_rejected(transport, tmp_path, mode):
    raw, *_ = packed(transport, tmp_path)
    parent = tmp_path / 'linked-parent'
    parent.symlink_to(tmp_path / 'packed', target_is_directory=True)
    inputs, *_ = transport
    with pytest.raises(T.TransportError, match='output_parent'):
        if mode == 'pack': T.pack_transport(**inputs, output=parent / 'failed')
        else:
            archive = tmp_path / 'transport.zip'
            archive.write_bytes(raw)
            T.unpack_transport(archive=archive, expected_sha256=P.digest(raw),
                               output=parent / 'failed')
    assert not (tmp_path / 'packed' / 'failed').exists()
