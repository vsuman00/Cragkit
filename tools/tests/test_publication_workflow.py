"""Release admission and partial-upload plans never infer publication authority."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publication_workflow as W


def admitted():
    return dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='vsuman00/Cragkit', GITHUB_ACTOR='vsuman00',
                GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_REF='refs/heads/main',
                GITHUB_RUN_ATTEMPT='1', REPOSITORY_PRIVATE='true',
                PUBLICATION_AUTHORIZED='true', RUNNER_COST_ACKNOWLEDGED='true',
                REGISTRY_SETUP_CONFIRMED='true', CRAGKIT_RELEASE_ENABLED='reviewed-rc1',
                GITHUB_SHA='a' * 40, REVIEWED_WORKFLOW_SHA='a' * 40,
                TRANSPORT_RELEASE_ID='123', TRANSPORT_ASSET_ID='456')


@pytest.fixture
def reviewed_policy(tmp_path, monkeypatch):
    approved = W.R.parse_json(W.P.read_file(W.POLICY, 16 * 1024))
    approved['security_hold'] = False
    path = tmp_path / 'reviewed-publication-policy.json'
    path.write_text(json.dumps(approved))
    monkeypatch.setattr(W, 'POLICY', path)
    return approved


def test_current_frozen_products_remain_on_security_hold():
    assert W.policy()['security_hold'] is True
    with pytest.raises(W.P.PreparationError, match='publication_security_hold'):
        W.admit(admitted())


@pytest.mark.parametrize('state,value', [('held', True), ('missing', None), ('null', None),
    ('string', 'false'), ('zero', 0), ('one', 1), ('list', []), ('object', {})])
def test_security_hold_refuses_perfect_environment_before_product_access(tmp_path, monkeypatch, state, value):
    approved = W.R.parse_json(W.P.read_file(W.POLICY, 16 * 1024))
    if state == 'missing':
        approved.pop('security_hold')
    else:
        approved['security_hold'] = value
    path = tmp_path / 'held-publication-policy.json'
    path.write_text(json.dumps(approved))
    monkeypatch.setattr(W, 'POLICY', path)
    monkeypatch.setattr(W, 'checked_products', lambda *args: pytest.fail('product access while held'))
    with pytest.raises(W.P.PreparationError, match='security_hold'):
        W.admit(admitted())
    with pytest.raises(W.P.PreparationError, match='security_hold'):
        W.publish_npm(prepared=Path('/unused'), plan_path=Path('/unused'),
                      environment=admitted(), runner=lambda *args, **kwargs: pytest.fail('upload while held'))


def test_reviewed_false_policy_allows_environment_validation(reviewed_policy):
    assert W.policy()['security_hold'] is False
    W.admit(admitted())


@pytest.mark.parametrize('key', list(admitted()))
def test_missing_admission_refuses_before_upload(key, reviewed_policy):
    environment = admitted()
    W.admit(environment)
    environment[key] = ''
    with pytest.raises(W.P.PreparationError):
        W.publish_npm(prepared=Path('/unused'), plan_path=Path('/unused'),
                      environment=environment, runner=lambda *a, **kw: pytest.fail('upload'))


@pytest.mark.parametrize('key,value', [('GITHUB_RUN_ATTEMPT', '2'),
    ('GITHUB_REF', 'refs/pull/1/merge'), ('REPOSITORY_PRIVATE', 'false'),
    ('GITHUB_REPOSITORY', 'attacker/Cragkit'), ('TRANSPORT_ASSET_ID', '1; upload'),
    ('GITHUB_ACTOR', 'someone-else'),
    ('REVIEWED_WORKFLOW_SHA', 'b' * 40), ('PUBLICATION_AUTHORIZED', True)])
def test_deceptive_context_cannot_admit(key, value, reviewed_policy):
    environment = admitted()
    environment[key] = value
    with pytest.raises(W.P.PreparationError):
        W.admit(environment)


def test_private_asset_must_belong_to_reviewed_draft(reviewed_policy):
    approved, environment = W.policy(), admitted()
    release = dict(id=123, draft=True, tag_name=approved['transport_tag'],
                   target_commitish='a' * 40, assets=[dict(id=456)])
    asset = dict(id=456, state='uploaded', name=approved['transport_asset'],
                 size=approved['transport_bytes'], digest='sha256:' + approved['transport_sha256'],
                 url='https://api.github.com/repos/vsuman00/Cragkit/releases/assets/456')
    W.validate_asset(release, asset, environment)
    for key, changed in [('draft', False), ('target_commitish', 'main'), ('assets', [])]:
        with pytest.raises(W.P.PreparationError):
            W.validate_asset(release | {key: changed}, asset, environment)
    for key, changed in [('id', 999), ('size', 1), ('digest', 'sha256:' + '0' * 64)]:
        with pytest.raises(W.P.PreparationError):
            W.validate_asset(release, asset | {key: changed}, environment)


@pytest.fixture
def packet(tmp_path, monkeypatch, reviewed_policy):
    products = [dict(item) for item in W.R.reviewed_products()]
    prepared, preflight = tmp_path / 'prepared', tmp_path / 'preflight'
    prepared.mkdir()
    preflight.mkdir()
    for item in products:
        raw = ('synthetic:' + item['path']).encode()
        item.update(bytes=len(raw), prepared_sha256=hashlib.sha256(raw).hexdigest())
        path = prepared / item['path']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    manifest = b'{"synthetic": true}\n'
    (prepared / W.P.MANIFEST_NAME).write_bytes(manifest)
    monkeypatch.setattr(W.R, 'MANIFEST_SHA256', hashlib.sha256(manifest).hexdigest())
    reviewed_policy['manifest_sha256'] = W.R.MANIFEST_SHA256
    W.POLICY.write_text(json.dumps(reviewed_policy))
    monkeypatch.setattr(W.R, 'reviewed_products', lambda: products)
    report = dict(revision='RPK-r1', manifest_sha256=W.R.MANIFEST_SHA256,
                  state='partial', products=[{key: item[key] for key in
                    ('path', 'registry', 'package', 'version', 'bytes')} |
                    dict(sha256=item['prepared_sha256'], state='absent') for item in products],
                  npm_next_tags=[dict(package=name, state='absent') for name in W.ORDER])
    path = preflight / 'registry-report.json'
    def save():
        path.write_text(json.dumps(report))
    save()
    return prepared, path, products, report, save


def test_missing_only_plan_and_upload_order(packet, tmp_path):
    prepared, report_path, products, report, save = packet
    verified = report['products'][0]
    assert verified['registry'] == 'npm'
    verified['state'] = 'verified'
    target = report_path.parent / verified['path']
    target.parent.mkdir(parents=True)
    target.write_bytes((prepared / verified['path']).read_bytes())
    next(item for item in report['npm_next_tags'] if item['package'] == verified['package'])['state'] = 'match'
    save()
    plan = W.prepare_uploads(prepared=prepared, report_path=report_path, output=tmp_path / 'upload')
    assert len(plan['missing']) == 8 and len(plan['npm_missing']) == 2
    assert all(plan['pypi_groups'].values())
    assert sorted(path.name for path in (tmp_path / 'upload/pypi/cragkit').iterdir()) == sorted(
        Path(item['path']).name for item in products if item['package'] == 'cragkit' and item['registry'] == 'pypi')
    calls = []
    W.publish_npm(prepared=prepared, plan_path=tmp_path / 'upload/workflow-plan.json',
                  environment=admitted(), runner=lambda command, **kw: calls.append((command, kw)))
    assert [Path(item[0][2]).name for item in calls] == [Path(path).name for path in plan['npm_missing']]
    assert all(item[0][3:] == ['--registry=https://registry.npmjs.org/', '--access=public',
        '--tag=next', '--ignore-scripts', '--provenance=false'] for item in calls)
    assert all(item[1] == dict(check=True, timeout=120) for item in calls)


@pytest.mark.parametrize('fault', ['extra', 'duplicate', 'drift', 'operation', 'tag', 'local_bytes', 'manifest'])
def test_bad_preflight_never_produces_upload_plan(packet, tmp_path, fault):
    prepared, report_path, products, report, save = packet
    if fault == 'extra': report['products'].append(dict(report['products'][0]))
    elif fault == 'duplicate': report['products'][1] = dict(report['products'][0])
    elif fault == 'drift': report['products'][0]['sha256'] = '0' * 64
    elif fault == 'operation': report['products'][0]['state'] = 'error'
    elif fault == 'tag': report['npm_next_tags'][0]['state'] = 'error'
    elif fault == 'local_bytes': (prepared / products[0]['path']).write_bytes(b'changed')
    else: (prepared / W.P.MANIFEST_NAME).write_bytes(b'changed')
    save()
    with pytest.raises((W.P.PreparationError, W.R.RegistryError)):
        W.prepare_uploads(prepared=prepared, report_path=report_path, output=tmp_path / 'upload')
    assert not (tmp_path / 'upload').exists()


def test_existing_output_and_failed_first_upload_are_preserved(packet, tmp_path):
    prepared, report_path, _, _, _ = packet
    output = tmp_path / 'upload'
    output.mkdir()
    (output / 'keep').write_bytes(b'keep')
    with pytest.raises(W.P.PreparationError, match='output_exists'):
        W.prepare_uploads(prepared=prepared, report_path=report_path, output=output)
    assert (output / 'keep').read_bytes() == b'keep'
    output = tmp_path / 'fresh'
    W.prepare_uploads(prepared=prepared, report_path=report_path, output=output)
    calls = []
    def fail(command, **kwargs):
        calls.append(command)
        raise subprocess.CalledProcessError(1, 'npm')
    with pytest.raises(subprocess.CalledProcessError):
        W.publish_npm(prepared=prepared, plan_path=output / 'workflow-plan.json',
                      environment=admitted(), runner=fail)
    assert len(calls) == 1 and Path(calls[0][2]).name == 'cragkit-1.0.0-rc.1.tgz'
