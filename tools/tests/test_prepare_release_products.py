"""Offline publication preparation preserves the independently checked candidate."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prepare_release_products as P
from test_check_ci_bundle import bundle, LICENSE, NOTICE, SOURCE


@pytest.fixture
def candidate(bundle, tmp_path, monkeypatch):
    files, run, jobs, artifact, archive, write, _ = bundle
    monkeypatch.setattr(P, 'SOURCE_COMMIT', SOURCE)
    monkeypatch.setattr(P, 'RUN_ID', 1)
    monkeypatch.setattr(P, 'JOB_ID', 2)
    monkeypatch.setattr(P, 'ARTIFACT_ID', 3)
    monkeypatch.setattr(P, 'ROOT', tmp_path)
    (tmp_path / 'LICENSE').write_bytes(LICENSE)
    (tmp_path / 'NOTICE').write_bytes(NOTICE)
    inputs = dict(archive=archive)

    def refresh():
        monkeypatch.setattr(P, 'BUNDLE_SHA256', write())
        for name, value in (('run', run), ('jobs', jobs), ('artifact', artifact)):
            inputs[name] = tmp_path / (name + '.json')
            inputs[name].write_text(json.dumps(value))

    refresh()
    return inputs, files, run, jobs, artifact, refresh


def make_tar(entries):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for item, raw in entries:
            archive.addfile(item, io.BytesIO(raw) if item.isfile() else None)
    return stream.getvalue()


def tar_entry(name, raw=b'x', mode=0o644, kind=tarfile.REGTYPE):
    item = tarfile.TarInfo(name)
    item.mode, item.type = mode, kind
    item.size = len(raw) if item.isfile() else 0
    return item, raw


def test_nine_products_exact_python_bytes_and_only_npm_manifest_change(candidate, tmp_path):
    inputs, files, *_ = candidate
    original_zip = inputs['archive'].read_bytes()
    output = tmp_path / 'prepared'
    result = P.prepare_products(**inputs, output=output)
    assert result['revision'] == 'PPR-r1'
    assert result['state'] == 'prepared_local'
    assert result['publication_authorized'] is result['published'] is False
    assert len(result['products']) == 9
    assert len(result['retained_evidence']['rebuilt_wheels']) == 3
    assert len(list((output / 'products/pypi').iterdir())) == 6
    assert len(list((output / 'products/npm').iterdir())) == 3
    assert inputs['archive'].read_bytes() == original_zip
    for record in result['products']:
        original = files[record['source_path']]
        prepared = (output / record['path']).read_bytes()
        if record['registry'] == 'pypi':
            assert prepared == original
            assert record['original'] == record['prepared']
        else:
            before = P.members(original, 'npm')
            after = P.members(prepared, 'npm')
            assert [(item.name, item.mode) for item in before] == [(item.name, item.mode) for item in after]
            for old, new in zip(before, after):
                if old.name == 'package/package.json':
                    project = P.CI.parse_json(old.content)
                    project['private'] = False
                    assert P.CI.parse_json(new.content) == project
                else:
                    assert new.content == old.content
            assert record['transformation'] == P.TRANSFORMATION
    assert P.verify_products(**inputs, prepared=output) == result


def test_two_preparations_have_identical_archives_and_manifests(candidate, tmp_path):
    inputs, *_ = candidate
    first, second = tmp_path / 'one', tmp_path / 'two'
    P.prepare_products(**inputs, output=first)
    P.prepare_products(**inputs, output=second)
    left = {str(path.relative_to(first)): path.read_bytes() for path in first.rglob('*') if path.is_file()}
    right = {str(path.relative_to(second)): path.read_bytes() for path in second.rglob('*') if path.is_file()}
    assert left == right


@pytest.mark.parametrize('change', ['run', 'job', 'artifact', 'source', 'digest'])
def test_independently_pinned_ci_identity_is_required(candidate, tmp_path, change):
    inputs, _, run, jobs, artifact, refresh = candidate
    if change == 'run': run['id'] = 999
    if change == 'job': jobs['jobs'][0]['id'] = 999
    if change == 'artifact': artifact['id'] = 999
    if change == 'source': run['head_sha'] = 'b' * 40
    refresh()
    if change == 'digest': inputs['archive'].write_bytes(inputs['archive'].read_bytes() + b'drift')
    with pytest.raises(P.PreparationError):
        P.prepare_products(**inputs, output=tmp_path / 'prepared')
    assert not (tmp_path / 'prepared').exists()
    assert not list(tmp_path.glob('.cragkit-publication-*'))


@pytest.mark.parametrize('change', ['missing', 'extra', 'runtime', 'license', 'json',
                                   'manifest', 'rehash', 'extra_directory', 'link'])
def test_verification_rebuilds_expectations_instead_of_trusting_manifest(candidate, tmp_path, change):
    inputs, *_ = candidate
    output = tmp_path / 'prepared'
    result = P.prepare_products(**inputs, output=output)
    npm = next(record for record in result['products'] if record['registry'] == 'npm')
    target = output / npm['path']
    if change == 'missing': target.unlink()
    elif change == 'extra': (output / 'extra.tgz').write_bytes(b'x')
    elif change == 'extra_directory': (output / 'unused').mkdir()
    elif change == 'link':
        target.unlink()
        target.symlink_to(inputs['archive'])
    elif change == 'manifest':
        result['published'] = True
        (output / P.MANIFEST_NAME).write_bytes(P.encode_json(result))
    else:
        entries = P.members(target.read_bytes(), 'npm')
        chosen = ('package/LICENSE' if change == 'license' else 'package/package.json')
        if change == 'runtime':
            entries.append(P.Member('package/dist/index.js', b'drift', 0o755))
        else:
            entries = [P.Member(item.name, b'private-token' if item.name == chosen
                                else item.content, item.mode, item.directory) for item in entries]
        target.write_bytes(make_tar([tar_entry(item.name, item.content, item.mode)
                                     for item in entries]))
        if change == 'rehash':
            npm['prepared']['sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
            npm['prepared']['bytes'] = target.stat().st_size
            (output / P.MANIFEST_NAME).write_bytes(P.encode_json(result))
    with pytest.raises(P.PreparationError) as error:
        P.verify_products(**inputs, prepared=output)
    assert 'private-token' not in str(error.value)
    assert error.value.__context__ is None


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'package/../escape',
                                  'package//file', 'package/./file', 'package\\file',
                                  'package/.env', 'package/key.pem', 'package/control\x01'])
def test_unsafe_member_paths_are_rejected_without_extraction(name):
    with pytest.raises(Exception):
        P.members(make_tar([tar_entry(name)]), 'npm')


@pytest.mark.parametrize('kind', [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE,
                                 tarfile.CHRTYPE, tarfile.BLKTYPE])
def test_links_and_special_tar_members_are_rejected(kind):
    with pytest.raises(P.PreparationError, match='archive_special_member'):
        P.members(make_tar([tar_entry('package/link', kind=kind)]), 'npm')


def test_duplicate_and_file_directory_conflicts_are_rejected():
    for entries in ([tar_entry('package/file'), tar_entry('package/file')],
                    [tar_entry('package/file'), tar_entry('package/file', kind=tarfile.DIRTYPE)],
                    [tar_entry('package/file'), tar_entry('package/file/child')]):
        with pytest.raises(P.PreparationError):
            P.members(make_tar(entries), 'npm')


@pytest.mark.parametrize('raw', [b'{"private":true,"private":true}',
                                b'{"private":true,"number":NaN}',
                                b'{"private":true,"number":Infinity}',
                                b'{"private":true,"number":1e999}',
                                b'{"private":false}'])
def test_invalid_json_and_nonprivate_source_manifest_are_rejected(raw):
    with pytest.raises(Exception):
        P.repack_npm([P.Member('package/package.json', raw, 0o644)])


def test_npm_executable_modes_are_preserved():
    entries = [P.Member('package/bin.js', b'run', 0o755),
               P.Member('package/package.json', b'{"private":true}', 0o640)]
    prepared, actual, comparison = P.repack_npm(entries)
    assert actual[0].mode == 0o755 and actual[1].mode == 0o640
    assert comparison == P.file_view(entries)
    assert prepared == P.repack_npm(entries)[0]


@pytest.mark.parametrize('existing', ['directory', 'file', 'symlink', 'broken_symlink'])
def test_existing_output_is_refused_and_preserved(candidate, tmp_path, existing):
    inputs, *_ = candidate
    output = tmp_path / 'prepared'
    if existing == 'directory': output.mkdir()
    elif existing == 'file': output.write_bytes(b'keep')
    else: output.symlink_to(tmp_path / ('LICENSE' if existing == 'symlink' else 'missing'))
    with pytest.raises(P.PreparationError, match='output_exists'):
        P.prepare_products(**inputs, output=output)
    assert P.os.path.lexists(output)
    if existing == 'file': assert output.read_bytes() == b'keep'


def test_failed_staging_removes_only_its_own_directory(candidate, tmp_path, monkeypatch):
    inputs, *_ = candidate
    unrelated = tmp_path / '.cragkit-publication-user-owned'
    unrelated.mkdir()
    (unrelated / 'keep').write_bytes(b'keep')
    def fail(*args):
        raise RuntimeError('private-token')
    monkeypatch.setattr(P, 'verify_directory', fail)
    with pytest.raises(P.PreparationError) as error:
        P.prepare_products(**inputs, output=tmp_path / 'prepared')
    assert str(error.value) == 'publication_invalid'
    assert error.value.__context__ is None
    assert not (tmp_path / 'prepared').exists()
    assert list(tmp_path.glob('.cragkit-publication-*')) == [unrelated]
    assert (unrelated / 'keep').read_bytes() == b'keep'


def test_bounded_archive_counts_and_bytes(monkeypatch):
    raw = make_tar([tar_entry('package/one', b'abc'), tar_entry('package/two', b'abc')])
    monkeypatch.setattr(P, 'MAX_MEMBERS', 1)
    with pytest.raises(P.PreparationError, match='member_limit'): P.members(raw, 'npm')
    monkeypatch.setattr(P, 'MAX_MEMBERS', 10)
    monkeypatch.setattr(P, 'MAX_UNPACKED', 5)
    with pytest.raises(P.PreparationError, match='member_limit'): P.members(raw, 'npm')
    monkeypatch.setattr(P, 'MAX_TAR', 100)
    with pytest.raises(P.PreparationError, match='tar_size_limit'): P.members(raw, 'npm')


def test_cli_help_and_failed_input_have_no_side_effects(tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        P.main(['--help'])
    assert exit_info.value.code == 0
    assert 'prepare' in capsys.readouterr().out
    output = tmp_path / 'prepared'
    argv = ['prepare', '--output', str(output)]
    for name in ('archive', 'run', 'jobs', 'artifact'):
        argv += ['--' + name, str(tmp_path / 'missing')]
    assert P.main(argv) == 1
    message = json.loads(capsys.readouterr().out)
    assert message['state'] == 'failed'
    assert message['published'] is message['publication_authorized'] is False
    assert not output.exists()


def test_private_token_change_preserves_json_numbers_whitespace_and_escaped_key():
    raw = b'{ "nested": {"private": true}, "ratio": 0.123456789012345678901, "pri\\u0076ate" : true }\n'
    expected = raw.replace(b'"pri\\u0076ate" : true', b'"pri\\u0076ate" : false')
    assert P.public_manifest(raw) == expected


def test_destination_created_during_final_claim_is_preserved(candidate, tmp_path, monkeypatch):
    inputs, *_ = candidate
    output = tmp_path / 'prepared'
    original_mkdir = Path.mkdir
    def race(path, *args, **kwargs):
        if path == output:
            original_mkdir(path)
        return original_mkdir(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'mkdir', race)
    with pytest.raises(P.PreparationError):
        P.prepare_products(**inputs, output=output)
    assert output.is_dir() and list(output.iterdir()) == []
    assert not list(tmp_path.glob('.cragkit-publication-*'))


def test_failed_output_copy_preserves_foreign_files_and_has_no_manifest(candidate, tmp_path, monkeypatch):
    inputs, *_ = candidate
    output = tmp_path / 'prepared'
    original_link = P.os.link
    count = 0
    def fail_link(source, target, **kwargs):
        nonlocal count
        count += 1
        assert not (output / P.MANIFEST_NAME).exists()
        if count == 2:
            (output / 'foreign').write_bytes(b'keep')
            raise OSError('private-token')
        return original_link(source, target, **kwargs)
    monkeypatch.setattr(P.os, 'link', fail_link)
    with pytest.raises(P.PreparationError):
        P.prepare_products(**inputs, output=output)
    assert (output / 'foreign').read_bytes() == b'keep'
    assert sorted(path.name for path in output.iterdir()) == ['foreign']
    assert not list(tmp_path.glob('.cragkit-publication-*'))
