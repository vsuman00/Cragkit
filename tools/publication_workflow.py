"""Validate explicit workflow admission and plan only reviewed missing uploads."""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import zipfile

import check_registry_products as R
import prepare_release_products as P

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'evaluation/release/V6-publication.json'
ORDER = ('cragkit', 'cragkit-langchain', 'cragkit-mcp')


def policy():
    result = R.parse_json(P.read_file(POLICY, 16 * 1024))
    P.require(result['revision'] == 'PWP-r2' and result['repository'] == 'vsuman00/Cragkit'
              and result['manifest_sha256'] == R.MANIFEST_SHA256
              and result['npm_tag'] == 'next', 'publication_policy')
    P.require(type(result.get('security_hold')) is bool, 'publication_policy_security_hold')
    return result


def admit(environment):
    P.require(policy()['security_hold'] is False, 'publication_security_hold')
    expected = {
        'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'vsuman00/Cragkit',
        'GITHUB_ACTOR': 'vsuman00',
        'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/main',
        'GITHUB_RUN_ATTEMPT': '1', 'REPOSITORY_PRIVATE': 'true',
        'PUBLICATION_AUTHORIZED': 'true', 'RUNNER_COST_ACKNOWLEDGED': 'true',
        'REGISTRY_SETUP_CONFIRMED': 'true', 'CRAGKIT_RELEASE_ENABLED': 'reviewed-rc1'}
    P.require(all(environment.get(key) == value for key, value in expected.items()),
              'publication_not_admitted')
    source = environment.get('GITHUB_SHA', '')
    P.require(re.fullmatch('[0-9a-f]{40}', source) is not None
              and environment.get('REVIEWED_WORKFLOW_SHA') == source,
              'workflow_source_not_reviewed')
    selector(environment.get('PYPI_PROJECT'))
    pending = environment.get('PYPI_PENDING_PROJECT')
    P.require(pending in ('none', *ORDER) and
              (pending == 'none' or pending == environment['PYPI_PROJECT']), 'pending_project')
    for key in ('TRANSPORT_RELEASE_ID', 'TRANSPORT_ASSET_ID', 'GITHUB_RUN_ID', 'GITHUB_REPOSITORY_ID'):
        positive_id(environment.get(key))

    if 'TRANSPORT_ARTIFACT_ID' in environment:
        positive_id(environment.get('TRANSPORT_ARTIFACT_ID'))


def selector(value):
    P.require(value in ('all', *ORDER), 'pypi_project')
    return value


def positive_id(value):
    P.require(type(value) is str and re.fullmatch('[1-9][0-9]{0,19}', value) is not None,
              'transport_id')
    return int(value)


def validate_asset(release, asset, environment):
    admit(environment)
    approved = policy()
    P.require(release.get('id') == int(environment['TRANSPORT_RELEASE_ID'])
              and release.get('draft') is True
              and release.get('tag_name') == approved['transport_tag']
              and release.get('target_commitish') == environment['GITHUB_SHA'],
              'transport_release_identity')
    P.require(asset.get('id') == int(environment['TRANSPORT_ASSET_ID'])
              and asset.get('state') == 'uploaded'
              and asset.get('name') == approved['transport_asset']
              and asset.get('size') == approved['transport_bytes']
              and asset.get('url') == 'https://api.github.com/repos/vsuman00/Cragkit/releases/assets/'
                  + environment['TRANSPORT_ASSET_ID'], 'transport_asset_identity')
    P.require(asset.get('digest') in (None, 'sha256:' + approved['transport_sha256']),
              'transport_asset_digest')
    P.require(any(item.get('id') == asset['id'] for item in release.get('assets', [])),
              'transport_asset_release')


def checked_products(prepared):
    products = R.reviewed_products()
    manifest = P.read_file(prepared / P.MANIFEST_NAME, 4 * 1024 * 1024)
    P.require(P.digest(manifest) == R.MANIFEST_SHA256, 'prepared_manifest')
    for product in products:
        R.verify_bytes(P.read_file(prepared / product['path'], P.MAX_ARCHIVE), product)
    return products


def checked_report(report_path):
    products = R.reviewed_products()
    report = R.parse_json(P.read_file(report_path, 256 * 1024))
    P.require(report.get('revision') == 'RPK-r1'
              and report.get('manifest_sha256') == R.MANIFEST_SHA256
              and report.get('state') in ('partial', 'complete'), 'preflight_report')
    observed = report.get('products')
    P.require(type(observed) is list and len(observed) == len(products)
              and all(type(item) is dict for item in observed)
              and {item.get('path') for item in observed} == {item['path'] for item in products},
              'preflight_inventory')
    records = {item['path']: item for item in observed}
    tags = report.get('npm_next_tags')
    P.require(type(tags) is list and len(tags) == 3
              and all(type(item) is dict for item in tags)
              and {item.get('package') for item in tags} == set(ORDER), 'preflight_tags')
    tag_states = {}
    for tag in tags:
        P.require(tag.get('expected') == '1.0.0-rc.1'
                  and tag.get('state') in ('match', 'absent', 'different'), 'preflight_tags')
        observed_tag = tag.get('observed')
        P.require((tag['state'] == 'match' and observed_tag == tag['expected'])
                  or (tag['state'] == 'absent' and observed_tag is None)
                  or (tag['state'] == 'different' and type(observed_tag) is str
                      and re.fullmatch(r'[A-Za-z0-9.+-]{1,128}', observed_tag) is not None
                      and observed_tag != tag['expected']), 'preflight_tags')
        tag_states[tag['package']] = tag['state']
    missing = []
    for product in products:
        record = records[product['path']]
        P.require(all(record.get(key) == product[key] for key in ('registry', 'package', 'version', 'bytes'))
                  and type(record.get('bytes')) is int
                  and record.get('sha256') == product['prepared_sha256']
                  and record.get('state') in ('verified', 'absent'), 'preflight_identity')
        if record['state'] == 'verified':
            R.verify_bytes(P.read_file(report_path.parent / product['path'], P.MAX_ARCHIVE), product)
        else:
            missing.append(product['path'])
        if product['registry'] == 'npm':
            allowed = ('match',) if record['state'] == 'verified' else ('absent', 'different')
            P.require(tag_states[product['package']] in allowed, 'npm_tag_requires_review')
    return products, missing


def required_paths(products, pypi_project):
    selector(pypi_project)
    return {item['path'] for item in products if pypi_project == 'all'
            or item['registry'] == 'npm' or item['package'] == pypi_project
            or (pypi_project != 'cragkit' and item['package'] == 'cragkit')}


def prepare_uploads(*, prepared, report_path, output, pypi_project):
    selector(pypi_project)
    P.require(not os.path.lexists(output), 'output_exists')
    checked_products(prepared)
    products, all_missing = checked_report(report_path)
    if pypi_project != 'all':
        dependencies = {item['path'] for item in products if item['registry'] == 'npm'
                        or (pypi_project != 'cragkit' and item['package'] == 'cragkit')}
        P.require(not dependencies.intersection(all_missing), 'phase_dependencies')
    missing = [item['path'] for item in products if item['path'] in all_missing
               and (pypi_project == 'all' or
                    (item['registry'] == 'pypi' and item['package'] == pypi_project))]
    files = {}
    for product in products:
        if product['path'] in missing and product['registry'] == 'pypi':
            target = 'pypi/' + product['package'] + '/' + Path(product['path']).name
            files[target] = P.read_file(prepared / product['path'], P.MAX_ARCHIVE)
    npm_missing = [item['path'] for name in ORDER for item in products
                   if item['registry'] == 'npm' and item['package'] == name and item['path'] in missing]
    plan = dict(revision='PUP-r2', state='planned_missing_only', pypi_project=pypi_project,
                manifest_sha256=R.MANIFEST_SHA256, all_missing=all_missing,
                missing=missing, npm_missing=npm_missing,
                pypi_groups={name: any(path.startswith('pypi/' + name + '/') for path in files)
                             for name in ORDER}, published=False)
    files['workflow-plan.json'] = P.encode_json(plan)
    expose_directory(output, files, 'workflow-plan.json')
    return plan


def expose_directory(output, files, marker):
    P.require(not os.path.lexists(output), 'output_exists')
    P.require(output.parent.is_dir() and not any(path.is_symlink()
              for path in (output.parent, *output.parent.parents)), 'output_parent')
    stage = Path(tempfile.mkdtemp(prefix='.cragkit-publication-', dir=output.parent))
    try:
        for name, raw in files.items():
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            path.chmod(0o600)
        P.publish_directory(stage, output, files, completion_marker=marker)
    finally:
        shutil.rmtree(stage)


def verify_postflight(*, report_path, pypi_project):
    selector(pypi_project)
    products, missing = checked_report(report_path)
    return dict(revision='PUP-r2', pypi_project=pypi_project,
                phase_complete=not required_paths(products, pypi_project).intersection(missing),
                publication_complete=not missing)


MAX_WRAPPER = 4 * 1024 * 1024


def validate_transport_artifact(metadata, environment):
    admit(environment)
    artifact_id = positive_id(environment.get('TRANSPORT_ARTIFACT_ID'))
    approved = policy()
    P.require(type(metadata.get('id')) is int and metadata['id'] == artifact_id
              and metadata.get('name') == 'reviewed-rc1-transport-' + environment['GITHUB_RUN_ID']
              and metadata.get('expired') is False
              and type(metadata.get('size_in_bytes')) is int
              and 0 < metadata['size_in_bytes'] <= MAX_WRAPPER
              and metadata.get('archive_download_url') ==
                  'https://api.github.com/repos/' + approved['repository']
                  + '/actions/artifacts/' + str(artifact_id) + '/zip', 'transport_artifact')
    run = metadata.get('workflow_run')
    P.require(type(run) is dict, 'transport_artifact_run')
    for key, expected in (('id', int(environment['GITHUB_RUN_ID'])),
                          ('repository_id', int(environment['GITHUB_REPOSITORY_ID'])),
                          ('head_repository_id', int(environment['GITHUB_REPOSITORY_ID']))):
        P.require(type(run.get(key)) is int and run[key] == expected, 'transport_artifact_run')
    P.require(run.get('head_branch') == 'main' and run.get('head_sha') == environment['GITHUB_SHA'],
              'transport_artifact_source')


def unwrap_transport_artifact(*, archive, output):
    P.require(not os.path.lexists(output), 'output_exists')
    raw = P.read_file(archive, MAX_WRAPPER)
    approved = policy()
    name = approved['transport_asset']
    try:
        P.require(len(raw) >= 22, 'artifact_zip')
        end = struct.unpack('<4s4H2LH', raw[-22:])
        P.require(end[0] == b'PK\x05\x06' and end[1:3] == (0, 0)
                  and end[3:5] == (1, 1) and end[7] == 0, 'artifact_inventory')
        with zipfile.ZipFile(io.BytesIO(raw)) as wrapper:
            entries = wrapper.infolist()
            P.require(len(entries) == 1, 'artifact_inventory')
            entry = entries[0]
            P.require(entry.filename == name and not entry.is_dir()
                      and stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFREG
                      and not entry.flag_bits & 1
                      and entry.file_size == approved['transport_bytes']
                      and entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                      'artifact_member')
            with wrapper.open(entry) as source:
                inner = source.read(approved['transport_bytes'] + 1)
            P.require(len(inner) == approved['transport_bytes']
                      and P.digest(inner) == approved['transport_sha256'], 'artifact_inner_digest')
    except P.PreparationError:
        raise
    except Exception:
        raise P.PreparationError('artifact_zip') from None
    expose_directory(output, {name: inner}, name)


def publish_npm(*, prepared, plan_path, environment, runner=subprocess.run):
    admit(environment)
    positive_id(environment.get('TRANSPORT_ARTIFACT_ID'))
    products = checked_products(prepared)
    plan = R.parse_json(P.read_file(plan_path, 32 * 1024))
    P.require(plan.get('revision') == 'PUP-r2'
              and plan.get('pypi_project') == environment['PYPI_PROJECT']
              and plan.get('manifest_sha256') == R.MANIFEST_SHA256,
              'upload_plan')
    selected = plan.get('npm_missing')
    expected_order = [item['path'] for name in ORDER for item in products
                      if item['registry'] == 'npm' and item['package'] == name]
    P.require(type(selected) is list and selected == [path for path in expected_order if path in selected],
              'npm_upload_inventory')
    if environment['PYPI_PROJECT'] != 'all':
        allowed = {item['path'] for item in products if item['registry'] == 'pypi'
                   and item['package'] == environment['PYPI_PROJECT']}
        P.require(not selected and type(plan.get('missing')) is list
                  and all(path in allowed for path in plan['missing']), 'phase_npm_forbidden')
    for relative in selected:
        runner(['npm', 'publish', str((prepared / relative).resolve()),
                '--registry=https://registry.npmjs.org/', '--access=public',
                '--tag=next', '--ignore-scripts', '--provenance=false'],
               check=True, timeout=120)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    modes.add_parser('guard')
    asset = modes.add_parser('asset')
    asset.add_argument('--release', type=Path, required=True)
    asset.add_argument('--asset', type=Path, required=True)
    artifact = modes.add_parser('artifact')
    artifact.add_argument('--metadata', type=Path, required=True)
    unwrap = modes.add_parser('unwrap-artifact')
    unwrap.add_argument('--archive', type=Path, required=True)
    unwrap.add_argument('--output', type=Path, required=True)
    plan = modes.add_parser('plan')
    for name in ('prepared', 'report', 'output'):
        plan.add_argument('--' + name, type=Path, required=True)
    plan.add_argument('--pypi-project', required=True)
    post = modes.add_parser('postflight')
    post.add_argument('--report', type=Path, required=True)
    post.add_argument('--pypi-project', required=True)
    npm = modes.add_parser('npm')
    npm.add_argument('--prepared', type=Path, required=True)
    npm.add_argument('--plan', type=Path, required=True)
    args = parser.parse_args(argv)
    status, result = 0, {}
    try:
        if args.mode == 'guard':
            admit(os.environ)
        elif args.mode == 'asset':
            validate_asset(R.parse_json(P.read_file(args.release, 1024 * 1024)),
                           R.parse_json(P.read_file(args.asset, 64 * 1024)), os.environ)
        elif args.mode == 'artifact':
            validate_transport_artifact(R.parse_json(P.read_file(args.metadata, 64 * 1024)), os.environ)
        elif args.mode == 'unwrap-artifact':
            admit(os.environ)
            positive_id(os.environ.get('TRANSPORT_ARTIFACT_ID'))
            unwrap_transport_artifact(archive=args.archive, output=args.output)
        elif args.mode == 'postflight':
            result = verify_postflight(report_path=args.report, pypi_project=args.pypi_project)
            status = 0 if result['phase_complete'] else 2
        elif args.mode == 'plan':
            admit(os.environ)
            P.require(args.pypi_project == os.environ['PYPI_PROJECT'], 'phase_scope')
            result = prepare_uploads(prepared=args.prepared, report_path=args.report,
                                     output=args.output, pypi_project=args.pypi_project)
            with Path(os.environ['GITHUB_OUTPUT']).open('a') as stream:
                for name, flag in zip(('pypi_core', 'pypi_langchain', 'pypi_mcp'),
                                      (result['pypi_groups'][name] for name in ORDER)):
                    stream.write(name + '=' + str(flag).lower() + '\n')
        else:
            publish_npm(prepared=args.prepared, plan_path=args.plan, environment=os.environ)
    except Exception:
        status = 1
        result = {}
    result.update(revision='PUP-r2', mode=args.mode,
                  state={0: 'passed', 1: 'failed', 2: 'pending'}[status])
    print(json.dumps(result))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
