"""Audit retained candidate CI bytes offline; never install or execute products."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile
import zipfile

from artifact_licensing import validate_artifact_licensing
from check_artifacts import archive_files, safe_member

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ('core', 'postgres', 'qdrant', 'qdrant-authoritative', 'tokenizers', 'mcp')
PACKAGES = (('sdks/core', 'cragkit'), ('sdks/frameworks', 'cragkit-langchain'),
            ('optional/mcp', 'cragkit-mcp'))
REPORTS = ('sdks/core/acceptance.json', 'sdks/frameworks/acceptance.json',
           'optional/acceptance.json')


class BundleError(ValueError):
    """A fixed diagnostic that never retains parser or product payloads."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise BundleError(code)


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'json_duplicate_key')
        result[key] = value
    return result


def _constant(_):
    raise BundleError('json_nonfinite')


def parse_json(raw: bytes):
    return json.loads(raw.decode('utf-8'), object_pairs_hook=_object, parse_constant=_constant)


def product_inventory():
    result = {}
    for prefix, package in PACKAGES:
        stem = package.replace('-', '_')
        if package == 'cragkit':
            stem = package
        result[f'{prefix}/python/{stem}-1.0.0rc1-py3-none-any.whl'] = ('wheel', package, 'wheel')
        result[f'{prefix}/python/{stem}-1.0.0rc1.tar.gz'] = ('sdist', package, 'sdist')
        result[f'{prefix}/rebuilt/{stem}-1.0.0rc1-py3-none-any.whl'] = ('wheel', package, 'rebuilt_wheel')
        result[f'{prefix}/npm/{package}-1.0.0-rc.1.tgz'] = ('npm', package, 'npm')
    return result


def _metadata(run, jobs, artifact, source, run_id, job_id, artifact_id, digest):
    require(re.fullmatch(r'[0-9a-f]{40}', source) is not None
            and re.fullmatch(r'[0-9a-f]{64}', digest) is not None, 'expected_identity')
    require(run['id'] == run_id and run['head_sha'] == source
            and run['head_commit']['id'] == source and run['run_attempt'] == 1
            and run['status'] == 'completed' and run['conclusion'] == 'success'
            and run['event'] == 'workflow_dispatch'
            and run['path'] == '.github/workflows/candidate-validation.yml'
            and run['repository']['full_name'] == 'vsuman00/Cragkit'
            and run['repository']['private'] is True, 'run_identity_or_state')
    require(jobs['total_count'] == 1 and len(jobs['jobs']) == 1, 'job_inventory')
    job = jobs['jobs'][0]
    require(job['id'] == job_id and job['run_id'] == run_id and job['head_sha'] == source
            and job['run_attempt'] == 1 and job['status'] == 'completed'
            and job['conclusion'] == 'success' and job['name'] == 'darwin-arm64'
            and job['labels'] == ['macos-15'], 'job_identity_or_state')
    required = {'Check out reviewed source', 'Pin npm and record runner identity',
                'Validate core and LangChain serially', 'Prepare optional MCP from frozen locks',
                'Validate MCP serially', 'Validate exact optional artifacts and installation profiles',
                'Retain candidate archives and reports'}
    steps = job['steps']
    require(required <= {step['name'] for step in steps}
            and all(step['status'] == 'completed' and step['conclusion'] == 'success'
                    for step in steps), 'job_steps')
    require(artifact['id'] == artifact_id and artifact['name'] == 'candidate-' + source
            and artifact['workflow_run']['id'] == run_id
            and artifact['workflow_run']['head_sha'] == source
            and artifact['digest'] == 'sha256:' + digest
            and artifact['expired'] is False, 'artifact_identity_or_state')


def _verify(archive, run, jobs, artifact, *, expected_source, expected_run,
            expected_job, expected_artifact, expected_digest, license_bytes, notice_bytes):
    _metadata(run, jobs, artifact, expected_source, expected_run, expected_job,
              expected_artifact, expected_digest)
    require(not archive.is_symlink() and archive.stat().st_size <= 16 * 1024 * 1024,
            'bundle_size_or_link')
    raw = archive.read_bytes()
    require(len(raw) == artifact['size_in_bytes']
            and hashlib.sha256(raw).hexdigest() == expected_digest, 'bundle_hash_or_size')
    inventory = product_inventory()
    files = {}
    with zipfile.ZipFile(archive) as outer:
        total = 0
        require(len(outer.infolist()) == len(inventory) + len(REPORTS), 'bundle_inventory')
        for member in outer.infolist():
            safe_member(member.filename)
            require(not member.is_dir() and member.filename not in files
                    and (member.external_attr >> 16) & 0o170000 != 0o120000,
                    'bundle_member')
            total += member.file_size
            require(total <= 64 * 1024 * 1024, 'bundle_unpacked_limit')
            files[member.filename] = outer.read(member)
    require(files.keys() == inventory.keys() | set(REPORTS), 'bundle_inventory')
    reports = {name: parse_json(files[name]) for name in REPORTS}
    for report in reports.values():
        require(report['state'] == 'passed' and bool(report['commands'])
                and all(command.get('returncode') == 0 for command in report['commands']),
                'acceptance_state')
    core, frameworks, optional = (reports[name] for name in REPORTS)
    require(core['rebuilt_wheel_files_identical'] is True
            and core['temporary_environments_cleaned'] is True
            and optional['temporary_environments_cleaned'] is True
            and core['installed_evidence']['state'] == 'passed'
            and core['installed_execution']['state'] == 'passed'
            and frameworks['python']['state'] == 'passed'
            and frameworks['node']['state'] == 'passed', 'installed_acceptance')
    require(set(core['imports']) == {'wheel', 'rebuilt_sdist_wheel', 'npm'}, 'import_inventory')
    require(set(optional['profiles']) == {'python', 'node'}
            and all(set(profiles) == set(PROFILES)
                    and all(value['state'] == 'passed' for value in profiles.values())
                    for profiles in optional['profiles'].values()), 'profile_acceptance')
    products = []
    wheels = {}
    with tempfile.TemporaryDirectory(prefix='cragkit-ci-audit-') as directory:
        for name, (kind, package, record_key) in inventory.items():
            if package == 'cragkit':
                record = core['artifacts'][record_key]
            elif package == 'cragkit-langchain':
                record = frameworks['node' if kind == 'npm' else 'python'][record_key]
            else:
                record = optional['artifacts'][record_key]
            content = files[name]
            digest = hashlib.sha256(content).hexdigest()
            require(record['path'].endswith('/artifacts/ci/' + name)
                    and record['bytes'] == len(content) and record['sha256'] == digest,
                    'product_hash_or_identity')
            path = Path(directory) / Path(name).name
            path.write_bytes(content)
            members = archive_files(path)
            require(record['file_count'] == len(members)
                    and record['unpacked_bytes'] == sum(map(len, members.values())),
                    'product_inventory')
            validate_artifact_licensing(members, kind=kind, package_name=package,
                version='1.0.0-rc.1' if kind == 'npm' else '1.0.0rc1',
                license_bytes=license_bytes, notice_bytes=notice_bytes)
            if kind == 'wheel':
                if package in wheels:
                    require(wheels[package] == members, 'rebuilt_wheel_drift')
                else:
                    wheels[package] = members
            products.append(dict(path=name, kind=kind, package=package, bytes=len(content),
                sha256=digest, file_count=len(members), unpacked_bytes=sum(map(len, members.values())),
                licensing='passed'))
    return dict(revision='CIB-r1', state='passed', source_commit=expected_source,
        run_id=expected_run, job_id=expected_job, artifact_id=expected_artifact,
        archive_sha256=expected_digest, archive_bytes=len(raw), products=products,
        acceptance_reports=[dict(path=name, sha256=hashlib.sha256(files[name]).hexdigest())
                            for name in REPORTS],
        optional_profiles={language: list(PROFILES) for language in ('python', 'node')},
        rebuilt_wheel_members_identical=True,
        license_sha256=hashlib.sha256(license_bytes).hexdigest(),
        notice_sha256=hashlib.sha256(notice_bytes).hexdigest())


def verify_bundle(*args, **kwargs):
    """Return only reviewed identity and counts; do not expose archive/parser data."""
    code = 'bundle_invalid'
    try:
        return _verify(*args, **kwargs)
    except BundleError as error:
        code = str(error)
    except Exception:
        pass
    # Leave the handler before raising, so private parser exceptions do not chain.
    raise BundleError(code)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'run', 'jobs', 'artifact', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--expected-source', required=True)
    parser.add_argument('--expected-digest', required=True)
    for name in ('run', 'job', 'artifact'):
        parser.add_argument('--expected-' + name, type=int, required=True)
    args = parser.parse_args(argv)
    failed = False
    try:
        result = verify_bundle(args.archive, parse_json(args.run.read_bytes()),
            parse_json(args.jobs.read_bytes()), parse_json(args.artifact.read_bytes()),
            expected_source=args.expected_source, expected_run=args.expected_run,
            expected_job=args.expected_job, expected_artifact=args.expected_artifact,
            expected_digest=args.expected_digest, license_bytes=(ROOT / 'LICENSE').read_bytes(),
            notice_bytes=(ROOT / 'NOTICE').read_bytes())
    except Exception:
        failed = True
    if failed:
        result = dict(revision='CIB-r1', state='failed', error='bundle_invalid')
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(state=result['state'])))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
