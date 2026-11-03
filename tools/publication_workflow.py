"""Validate explicit workflow admission and plan only reviewed missing uploads."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import check_registry_products as R
import prepare_release_products as P

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'evaluation/release/V6-publication.json'
ORDER = ('cragkit', 'cragkit-langchain', 'cragkit-mcp')


def policy():
    result = R.parse_json(P.read_file(POLICY, 16 * 1024))
    P.require(result['revision'] == 'PWP-r1' and result['repository'] == 'vsuman00/Cragkit'
              and result['manifest_sha256'] == R.MANIFEST_SHA256
              and result['npm_tag'] == 'next', 'publication_policy')
    return result


def admit(environment):
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
    for key in ('TRANSPORT_RELEASE_ID', 'TRANSPORT_ASSET_ID'):
        P.require(re.fullmatch('[1-9][0-9]{0,19}', environment.get(key, '')) is not None,
                  'transport_id')


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


def prepare_uploads(*, prepared, report_path, output):
    P.require(not os.path.lexists(output), 'output_exists')
    products = checked_products(prepared)
    report = R.parse_json(P.read_file(report_path, 256 * 1024))
    P.require(report.get('revision') == 'RPK-r1'
              and report.get('manifest_sha256') == R.MANIFEST_SHA256
              and report.get('state') in ('partial', 'complete'), 'preflight_report')
    observed = report.get('products', [])
    P.require(len(observed) == len(products)
              and {item.get('path') for item in observed} == {item['path'] for item in products},
              'preflight_inventory')
    records = {item['path']: item for item in observed}
    tags = report.get('npm_next_tags', [])
    P.require(len(tags) == 3 and {item.get('package') for item in tags} == set(ORDER),
              'preflight_tags')
    tag_states = {item['package']: item['state'] for item in tags}
    files, missing = {}, []
    for product in products:
        record = records[product['path']]
        P.require(all(record.get(key) == product[key] for key in ('registry', 'package', 'version', 'bytes'))
                  and record.get('sha256') == product['prepared_sha256']
                  and record.get('state') in ('verified', 'absent'), 'preflight_identity')
        if record['state'] == 'verified':
            R.verify_bytes(P.read_file(report_path.parent / product['path'], P.MAX_ARCHIVE), product)
        else:
            missing.append(product['path'])
            if product['registry'] == 'pypi':
                target = 'pypi/' + product['package'] + '/' + Path(product['path']).name
                files[target] = P.read_file(prepared / product['path'], P.MAX_ARCHIVE)
        if product['registry'] == 'npm':
            allowed = ('match',) if record['state'] == 'verified' else ('absent', 'different')
            P.require(tag_states[product['package']] in allowed, 'npm_tag_requires_review')
    npm_missing = [product['path'] for name in ORDER for product in products
                   if product['package'] == name and product['registry'] == 'npm'
                   and product['path'] in missing]
    plan = dict(revision='PUP-r1', state='planned_missing_only',
                manifest_sha256=R.MANIFEST_SHA256, missing=missing, npm_missing=npm_missing,
                pypi_groups={name: any(path.startswith('pypi/' + name + '/') for path in files)
                             for name in ORDER}, published=False)
    files['workflow-plan.json'] = P.encode_json(plan)
    stage = Path(tempfile.mkdtemp(prefix='.cragkit-upload-plan-', dir=output.parent))
    try:
        for name, raw in files.items():
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        P.publish_directory(stage, output, files, completion_marker='workflow-plan.json')
    finally:
        shutil.rmtree(stage)
    return plan


def publish_npm(*, prepared, plan_path, environment, runner=subprocess.run):
    admit(environment)
    products = checked_products(prepared)
    plan = R.parse_json(P.read_file(plan_path, 32 * 1024))
    P.require(plan.get('revision') == 'PUP-r1' and plan.get('manifest_sha256') == R.MANIFEST_SHA256,
              'upload_plan')
    selected = plan.get('npm_missing')
    expected_order = [item['path'] for name in ORDER for item in products
                      if item['registry'] == 'npm' and item['package'] == name]
    P.require(type(selected) is list and selected == [path for path in expected_order if path in selected],
              'npm_upload_inventory')
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
    plan = modes.add_parser('plan')
    for name in ('prepared', 'report', 'output'):
        plan.add_argument('--' + name, type=Path, required=True)
    npm = modes.add_parser('npm')
    npm.add_argument('--prepared', type=Path, required=True)
    npm.add_argument('--plan', type=Path, required=True)
    args = parser.parse_args(argv)
    failed = False
    try:
        if args.mode == 'guard':
            admit(os.environ)
        elif args.mode == 'asset':
            validate_asset(R.parse_json(P.read_file(args.release, 1024 * 1024)),
                           R.parse_json(P.read_file(args.asset, 64 * 1024)), os.environ)
        elif args.mode == 'plan':
            admit(os.environ)
            result = prepare_uploads(prepared=args.prepared, report_path=args.report, output=args.output)
            with Path(os.environ['GITHUB_OUTPUT']).open('a') as stream:
                for name, flag in zip(('pypi_core', 'pypi_langchain', 'pypi_mcp'),
                                      (result['pypi_groups'][name] for name in ORDER)):
                    stream.write(name + '=' + str(flag).lower() + '\n')
        else:
            publish_npm(prepared=args.prepared, plan_path=args.plan, environment=os.environ)
    except Exception:
        failed = True
    print(json.dumps(dict(revision='PUP-r1', mode=args.mode, state='failed' if failed else 'passed')))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
