"""Small offline bundles exercise identity, payload and acceptance failure paths."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_ci_bundle as CI

SOURCE = 'a' * 40
LICENSE = b'synthetic license\n'
NOTICE = b'synthetic notice\n'


def product(kind, package):
    stem = package.replace('-', '_')
    if kind == 'wheel':
        prefix = f'{stem}-1.0.0rc1.dist-info/'
        members = {prefix + 'METADATA': (
            f'Metadata-Version: 2.5\nName: {package}\nVersion: 1.0.0rc1\n'
            'License-Expression: MIT\nLicense-File: LICENSE\nLicense-File: NOTICE\n\n').encode(),
            prefix + 'licenses/LICENSE': LICENSE, prefix + 'licenses/NOTICE': NOTICE}
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for name, raw in members.items():
                archive.writestr(name, raw)
    else:
        if kind == 'npm':
            prefix = 'package/'
            metadata = json.dumps(dict(name=package, version='1.0.0-rc.1', license='MIT',
                private=True, files=['dist', 'LICENSE', 'NOTICE'])).encode()
            name = 'package.json'
        else:
            prefix = f'{stem}-1.0.0rc1/'
            metadata = (f'[project]\nname = "{package}"\nversion = "1.0.0rc1"\n'
                'license = "MIT"\nlicense-files = ["LICENSE", "NOTICE"]\n').encode()
            name = 'pyproject.toml'
        members = {prefix + name: metadata, prefix + 'LICENSE': LICENSE, prefix + 'NOTICE': NOTICE}
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            for name, raw in members.items():
                item = tarfile.TarInfo(name)
                item.size = len(raw)
                archive.addfile(item, io.BytesIO(raw))
    return stream.getvalue(), members


@pytest.fixture
def bundle(tmp_path):
    core = dict(state='passed', commands=[dict(returncode=0)], artifacts={},
        rebuilt_wheel_files_identical=True, temporary_environments_cleaned=True,
        installed_evidence=dict(state='passed'), installed_execution=dict(state='passed'),
        imports={name: {} for name in ('wheel', 'rebuilt_sdist_wheel', 'npm')})
    frameworks = dict(state='passed', commands=[dict(returncode=0)],
        python=dict(state='passed'), node=dict(state='passed'))
    optional = dict(state='passed', commands=[dict(returncode=0)], artifacts={},
        temporary_environments_cleaned=True,
        profiles={lang: {profile: dict(state='passed') for profile in CI.PROFILES}
                  for lang in ('python', 'node')})
    files = {}
    for name, (kind, package, key) in CI.product_inventory().items():
        raw, members = product(kind, package)
        files[name] = raw
        record = dict(path='/runner/artifacts/ci/' + name, bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(), file_count=len(members),
            unpacked_bytes=sum(map(len, members.values())))
        destination = (core['artifacts'] if package == 'cragkit' else
            frameworks['node' if kind == 'npm' else 'python'] if package == 'cragkit-langchain'
            else optional['artifacts'])
        destination[key] = record
    for name, report in zip(CI.REPORTS, (core, frameworks, optional)):
        files[name] = json.dumps(report).encode()
    run = dict(id=1, head_sha=SOURCE, head_commit=dict(id=SOURCE), run_attempt=1,
        status='completed', conclusion='success', event='workflow_dispatch',
        path='.github/workflows/candidate-validation.yml',
        repository=dict(full_name='vsuman00/Cragkit', private=True))
    steps = ['Check out reviewed source', 'Pin npm and record runner identity',
        'Validate core and LangChain serially', 'Prepare optional MCP from frozen locks',
        'Validate MCP serially', 'Validate exact optional artifacts and installation profiles',
        'Retain candidate archives and reports']
    jobs = dict(total_count=1, jobs=[dict(id=2, run_id=1, head_sha=SOURCE, run_attempt=1,
        status='completed', conclusion='success', name='darwin-arm64', labels=['macos-15'],
        steps=[dict(name=name, status='completed', conclusion='success') for name in steps])])
    artifact = dict(id=3, name='candidate-' + SOURCE, workflow_run=dict(id=1, head_sha=SOURCE),
        expired=False)
    archive = tmp_path / 'bundle.zip'

    def write():
        with zipfile.ZipFile(archive, 'w') as outer:
            for name, raw in files.items():
                outer.writestr(name, raw)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        artifact.update(digest='sha256:' + digest, size_in_bytes=archive.stat().st_size)
        return digest

    def verify():
        return CI.verify_bundle(archive, run, jobs, artifact, expected_source=SOURCE,
            expected_run=1, expected_job=2, expected_artifact=3,
            expected_digest=artifact['digest'][7:], license_bytes=LICENSE, notice_bytes=NOTICE)

    write()
    return files, run, jobs, artifact, archive, write, verify


def test_retained_bundle_binds_all_products_and_profiles(bundle):
    *_, verify = bundle
    result = verify()
    assert result['state'] == 'passed'
    assert len(result['products']) == 12
    assert result['rebuilt_wheel_members_identical'] is True
    assert result['optional_profiles']['python'] == list(CI.PROFILES)


@pytest.mark.parametrize('field', ['source', 'run', 'job', 'artifact', 'state', 'private', 'expired'])
def test_metadata_identity_and_state_cannot_drift(bundle, field):
    _, run, jobs, artifact, _, _, verify = bundle
    if field == 'source': run['head_sha'] = 'b' * 40
    if field == 'run': run['id'] = 9
    if field == 'job': jobs['jobs'][0]['id'] = 9
    if field == 'artifact': artifact['id'] = 9
    if field == 'state': jobs['jobs'][0]['steps'][0]['conclusion'] = 'skipped'
    if field == 'private': run['repository']['private'] = False
    if field == 'expired': artifact['expired'] = True
    with pytest.raises(CI.BundleError): verify()


def test_outer_bytes_must_match_retained_digest(bundle):
    _, _, _, _, path, _, verify = bundle
    path.write_bytes(path.read_bytes() + b'tamper')
    with pytest.raises(CI.BundleError, match='bundle_hash_or_size'): verify()


@pytest.mark.parametrize('change', ['missing', 'extra', 'product', 'hash', 'state', 'profile', 'unsafe'])
def test_inner_inventory_hash_and_acceptance_fail_closed(bundle, change):
    files, _, _, _, _, write, verify = bundle
    name = next(iter(CI.product_inventory()))
    if change == 'missing': del files[name]
    if change == 'extra': files['unexpected.txt'] = b'private-token'
    if change == 'product': files[name] += b'tamper'
    if change == 'unsafe':
        files['../private-token'] = files.pop(name)
    if change in ('hash', 'state', 'profile'):
        report_name = 'optional/acceptance.json' if change == 'profile' else CI.REPORTS[0]
        report = json.loads(files[report_name])
        if change == 'hash': report['artifacts']['wheel']['sha256'] = '0' * 64
        if change == 'state': report['state'] = 'failed'
        if change == 'profile': report['profiles']['node']['mcp']['state'] = 'failed'
        files[report_name] = json.dumps(report).encode()
    write()
    with pytest.raises(CI.BundleError) as error: verify()
    assert 'private-token' not in str(error.value)
    assert error.value.__context__ is None


def test_license_bytes_must_match_source_assets(bundle):
    _, run, jobs, artifact, path, _, _ = bundle
    with pytest.raises(CI.BundleError, match='bundle_invalid'):
        CI.verify_bundle(path, run, jobs, artifact, expected_source=SOURCE,
            expected_run=1, expected_job=2, expected_artifact=3,
            expected_digest=artifact['digest'][7:], license_bytes=b'wrong', notice_bytes=NOTICE)


@pytest.mark.parametrize('member', ['cragkit/.env', 'cragkit/extra.py'])
def test_rehashed_inner_archive_cannot_hide_secrets_or_rebuild_drift(bundle, member):
    files, _, _, _, _, write, verify = bundle
    name = 'sdks/core/rebuilt/cragkit-1.0.0rc1-py3-none-any.whl'
    source = io.BytesIO(files[name])
    with zipfile.ZipFile(source) as archive:
        members = {entry.filename: archive.read(entry) for entry in archive.infolist()}
    members[member] = b'private-token'
    target = io.BytesIO()
    with zipfile.ZipFile(target, 'w') as archive:
        for path, raw in members.items(): archive.writestr(path, raw)
    files[name] = target.getvalue()
    report = json.loads(files[CI.REPORTS[0]])
    report['artifacts']['rebuilt_wheel'].update(bytes=len(files[name]),
        sha256=hashlib.sha256(files[name]).hexdigest(), file_count=len(members),
        unpacked_bytes=sum(map(len, members.values())))
    files[CI.REPORTS[0]] = json.dumps(report).encode()
    write()
    with pytest.raises(CI.BundleError) as error: verify()
    assert 'private-token' not in str(error.value)
    assert error.value.__context__ is None


def test_malformed_private_json_never_leaks_exception_context(bundle):
    files, _, _, _, _, write, verify = bundle
    files[CI.REPORTS[0]] = b'{private-token'
    write()
    with pytest.raises(CI.BundleError) as error: verify()
    assert str(error.value) == 'bundle_invalid'
    assert error.value.__context__ is None


def test_json_rejects_duplicate_keys_and_nonfinite_values():
    for raw in (b'{"state":"passed","state":"failed"}', b'{"number":NaN}'):
        with pytest.raises(CI.BundleError): CI.parse_json(raw)
