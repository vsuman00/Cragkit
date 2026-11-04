"""Release admission and partial-upload plans never infer publication authority."""
import hashlib
import json
import io
import zipfile
import stat
from pathlib import Path
import re
import shlex
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
                TRANSPORT_RELEASE_ID='123', TRANSPORT_ASSET_ID='456',
                PYPI_PROJECT='all', PYPI_PENDING_PROJECT='none', GITHUB_RUN_ID='789',
                GITHUB_REPOSITORY_ID='321', TRANSPORT_ARTIFACT_ID='987')


@pytest.fixture
def reviewed_policy(tmp_path, monkeypatch):
    approved = W.R.parse_json(W.P.read_file(W.POLICY, 16 * 1024))
    approved['security_hold'] = False
    approved['revision'] = 'PWP-r2'
    path = tmp_path / 'reviewed-publication-policy.json'
    path.write_text(json.dumps(approved))
    monkeypatch.setattr(W, 'POLICY', path)
    return approved


def test_executable_transport_command_matches_reviewed_policy_and_admission_order():
    approved = W.policy()
    workflow_path = Path(__file__).resolve().parents[2] / '.github/workflows' / approved['workflow']
    workflow = workflow_path.read_text()
    # Inspect executable folded run blocks, rather than matching a digest in a comment.
    commands = [shlex.split(block) for block in re.findall(
        r'^        run: >-\n((?:          [^\n]*\n)+)', workflow, re.MULTILINE)]
    unpack = [command for command in commands
              if command[:3] == ['python', 'tools/release_transport.py', 'unpack']]
    assert len(unpack) == 1
    assert unpack[0] == ['python', 'tools/release_transport.py', 'unpack',
                         '--archive', '.release-download/' + approved['transport_asset'],
                         '--expected-sha256', approved['transport_sha256'],
                         '--output', '.release-candidate']
    assert "github.repository == '" + approved['repository'] + "'" in workflow
    for gate in ("github.actor == 'vsuman00'", 'github.event.repository.private == true',
                 "github.ref == 'refs/heads/main'", 'github.run_attempt == 1',
                 'inputs.reviewed_workflow_sha == github.sha',
                 'inputs.publication_authorized && inputs.runner_cost_acknowledged',
                 "inputs.registry_setup_confirmed && vars.CRAGKIT_RELEASE_ENABLED == 'reviewed-rc1'"):
        assert gate in workflow
    assert 'pypi_project:' in workflow and 'pypi_pending_project:' in workflow
    assert 'PYPI_PROJECT:' in workflow and 'PYPI_PENDING_PROJECT:' in workflow
    # Identity comes from immutable runner defaults; workflows must not override them.
    assert not re.search(r'^      GITHUB_(?:RUN_ID|REPOSITORY_ID):', workflow, re.MULTILINE)
    assert 'TRANSPORT_ARTIFACT_ID:' in workflow and 'needs.' in workflow
    assert 'head -c 4194305' in workflow and 'pipefail' in workflow
    assert '--pypi-project' in workflow
    assert 'unwrap-artifact' in workflow and 'postflight' in workflow
    # Read-only visibility retries must be downstream of the single publish action.
    assert workflow.count('uses: pypa/gh-action-pypi-publish@') == 3
    assert '15' in workflow and '10' in workflow
    jobs = re.split(r'^  (?=[A-Za-z][A-Za-z0-9_-]*:\n)', workflow, flags=re.MULTILINE)
    fetch = next(job for job in jobs if 'contents: write' in job)
    publisher = next(job for job in jobs if 'id-token: write' in job)
    assert fetch != publisher and 'id-token: none' in fetch
    assert 'contents: read' in publisher and 'actions: read' in publisher
    assert 'contents: write' not in publisher
    assert 'pypa/gh-action-pypi-publish' not in fetch and ' unpack' not in fetch
    for job in (fetch, publisher):
        assert 'publication_workflow.py guard' in job
        assert "github.actor == 'vsuman00'" in job
        assert 'inputs.reviewed_workflow_sha == github.sha' in job
    assert 'timeout-minutes: 5' in fetch and 'timeout-minutes: 20' in publisher


def test_reviewed_bootstrap_clearance_does_not_admit_unconfigured_hosted_publication():
    approved = W.policy()
    assert approved['security_hold'] is False
    assert approved['publication_authorized'] is True
    assert approved['workflow_dispatched'] is True
    for key in ('REGISTRY_SETUP_CONFIRMED', 'CRAGKIT_RELEASE_ENABLED'):
        environment = admitted()
        environment[key] = ''
        with pytest.raises(W.P.PreparationError, match='publication_not_admitted'):
            W.admit(environment)


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
                  npm_next_tags=[dict(package=name, expected='1.0.0-rc.1', observed=None, state='absent') for name in W.ORDER])
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
    next(item for item in report['npm_next_tags'] if item['package'] == verified['package']).update(
        state='match', observed='1.0.0-rc.1')
    save()
    plan = W.prepare_uploads(prepared=prepared, report_path=report_path, output=tmp_path / 'upload', pypi_project='all')
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
        W.prepare_uploads(prepared=prepared, report_path=report_path, output=tmp_path / 'upload', pypi_project='all')
    assert not (tmp_path / 'upload').exists()


def test_existing_output_and_failed_first_upload_are_preserved(packet, tmp_path):
    prepared, report_path, _, _, _ = packet
    output = tmp_path / 'upload'
    output.mkdir()
    (output / 'keep').write_bytes(b'keep')
    with pytest.raises(W.P.PreparationError, match='output_exists'):
        W.prepare_uploads(prepared=prepared, report_path=report_path, output=output, pypi_project='all')
    assert (output / 'keep').read_bytes() == b'keep'
    output = tmp_path / 'fresh'
    W.prepare_uploads(prepared=prepared, report_path=report_path, output=output, pypi_project='all')
    calls = []
    def fail(command, **kwargs):
        calls.append(command)
        raise subprocess.CalledProcessError(1, 'npm')
    with pytest.raises(subprocess.CalledProcessError):
        W.publish_npm(prepared=prepared, plan_path=output / 'workflow-plan.json',
                      environment=admitted(), runner=fail)
    assert len(calls) == 1 and Path(calls[0][2]).name == 'cragkit-1.0.0-rc.1.tgz'


@pytest.mark.parametrize('selected,pending', [('', 'none'), ('unknown', 'none'),
    ('all', 'cragkit'), ('cragkit', 'cragkit-mcp'), ('cragkit', ''), ('cragkit', 'unknown')])
def test_selector_and_pending_conflicts_refuse_before_access(reviewed_policy, selected, pending):
    with pytest.raises(W.P.PreparationError):
        W.admit(admitted() | dict(PYPI_PROJECT=selected, PYPI_PENDING_PROJECT=pending))


@pytest.mark.parametrize('selected,pending', [('all', 'none'), ('cragkit', 'cragkit'),
    ('cragkit-langchain', 'none'), ('cragkit-mcp', 'cragkit-mcp')])
def test_selected_binding_is_admitted_without_claiming_all_bindings(reviewed_policy, selected, pending):
    W.admit(admitted() | dict(PYPI_PROJECT=selected, PYPI_PENDING_PROJECT=pending))


def verify_records(packet, predicate):
    prepared, report_path, _, report, save = packet
    for item in report['products']:
        if predicate(item):
            item['state'] = 'verified'
            path = report_path.parent / item['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((prepared / item['path']).read_bytes())
    for item in report['npm_next_tags']:
        if any(record['registry'] == 'npm' and record['package'] == item['package']
               and record['state'] == 'verified' for record in report['products']):
            item.update(state='match', observed='1.0.0-rc.1')
    report['state'] = 'complete' if all(item['state'] == 'verified' for item in report['products']) else 'partial'
    save()


@pytest.mark.parametrize('selected', ['cragkit', 'cragkit-langchain', 'cragkit-mcp'])
def test_selected_phase_only_authorizes_its_pair(packet, tmp_path, selected):
    verify_records(packet, lambda item: item['registry'] == 'npm' or
                   (selected != 'cragkit' and item['package'] == 'cragkit'))
    prepared, report_path, _, _, _ = packet
    output = tmp_path / 'phase'
    plan = W.prepare_uploads(prepared=prepared, report_path=report_path, output=output,
                             pypi_project=selected)
    assert plan['revision'] == 'PUP-r2' and plan['pypi_project'] == selected
    assert len(plan['missing']) == 2 and len(plan['all_missing']) >= 2
    assert plan['npm_missing'] == []
    assert all('/pypi/' in '/' + path and selected.replace('-', '_') in Path(path).name
               for path in plan['missing'])
    assert sum(path.is_file() for path in (output / 'pypi').rglob('*')) == 2
    calls = []
    W.publish_npm(prepared=prepared, plan_path=output / 'workflow-plan.json',
                  environment=admitted() | dict(PYPI_PROJECT=selected),
                  runner=lambda *a, **kw: calls.append(a))
    assert calls == []


@pytest.mark.parametrize('fault', ['missing_npm', 'missing_core', 'unselected_error', 'unselected_drift'])
def test_phase_dependencies_and_unselected_failures_block(packet, tmp_path, fault):
    verify_records(packet, lambda item: item['registry'] == 'npm' or item['package'] == 'cragkit')
    prepared, report_path, _, report, save = packet
    if fault == 'missing_npm':
        report['products'][0]['state'] = 'absent'
    elif fault == 'missing_core':
        next(item for item in report['products'] if item['registry'] == 'pypi' and item['package'] == 'cragkit')['state'] = 'absent'
    else:
        item = next(item for item in report['products'] if item['package'] == 'cragkit-mcp' and item['registry'] == 'pypi')
        item['state'] = 'error' if fault == 'unselected_error' else 'verified'
        if fault == 'unselected_drift':
            path = report_path.parent / item['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'wrong')
    save()
    with pytest.raises((W.P.PreparationError, W.R.RegistryError)):
        W.prepare_uploads(prepared=prepared, report_path=report_path, output=tmp_path / 'refused',
                          pypi_project='cragkit-langchain')
    assert not (tmp_path / 'refused').exists()


@pytest.mark.parametrize('fault', ['npm_injection', 'scope_mismatch'])
def test_tampered_phase_cannot_reach_npm_runner(packet, tmp_path, fault):
    verify_records(packet, lambda item: item['registry'] == 'npm')
    prepared, report_path, products, _, _ = packet
    output = tmp_path / 'phase'
    W.prepare_uploads(prepared=prepared, report_path=report_path, output=output, pypi_project='cragkit')
    path = output / 'workflow-plan.json'
    plan = json.loads(path.read_text())
    if fault == 'npm_injection':
        plan['npm_missing'] = [products[0]['path']]
        plan['missing'].append(products[0]['path'])
    else:
        plan['pypi_project'] = 'all'
    path.write_text(json.dumps(plan))
    with pytest.raises(W.P.PreparationError):
        W.publish_npm(prepared=prepared, plan_path=path,
                      environment=admitted() | dict(PYPI_PROJECT='cragkit'),
                      runner=lambda *a, **kw: pytest.fail('unexpected npm mutation'))


def test_postflight_distinguishes_complete_phase_from_complete_publication(packet):
    verify_records(packet, lambda item: item['registry'] == 'npm' or item['package'] == 'cragkit')
    _, report_path, _, _, _ = packet
    result = W.verify_postflight(report_path=report_path, pypi_project='cragkit')
    assert result['phase_complete'] is True and result['publication_complete'] is False
    result = W.verify_postflight(report_path=report_path, pypi_project='all')
    assert result['phase_complete'] is False and result['publication_complete'] is False
    verify_records(packet, lambda item: True)
    result = W.verify_postflight(report_path=report_path, pypi_project='all')
    assert result['phase_complete'] is True and result['publication_complete'] is True


def artifact_metadata():
    return dict(id=987, name='reviewed-rc1-transport-789', expired=False, size_in_bytes=1024,
                archive_download_url='https://api.github.com/repos/vsuman00/Cragkit/actions/artifacts/987/zip',
                workflow_run=dict(id=789, repository_id=321, head_repository_id=321,
                                  head_branch='main', head_sha='a' * 40))


@pytest.mark.parametrize('field,value', [('id', 988), ('name', 'foreign'), ('expired', True),
    ('expired', 0), ('size_in_bytes', 0), ('size_in_bytes', 4194305),
    ('archive_download_url', 'https://attacker.invalid/archive')])
def test_foreign_expired_or_unbounded_artifact_is_refused(reviewed_policy, field, value):
    metadata = artifact_metadata()
    W.validate_transport_artifact(metadata, admitted())
    with pytest.raises(W.P.PreparationError):
        W.validate_transport_artifact(metadata | {field: value}, admitted())


@pytest.mark.parametrize('field,value', [('id', 790), ('repository_id', 322),
    ('head_repository_id', 322), ('head_branch', 'other'), ('head_sha', 'b' * 40)])
def test_artifact_must_belong_to_same_reviewed_run_and_repository(reviewed_policy, field, value):
    metadata = artifact_metadata()
    metadata['workflow_run'][field] = value
    with pytest.raises(W.P.PreparationError):
        W.validate_transport_artifact(metadata, admitted())


@pytest.fixture
def sealed_wrapper(tmp_path, reviewed_policy):
    inner = b'fixed synthetic sealed transport'
    reviewed_policy.update(transport_bytes=len(inner), transport_sha256=hashlib.sha256(inner).hexdigest())
    W.POLICY.write_text(json.dumps(reviewed_policy))
    archive = tmp_path / 'artifact.zip'
    def write(members=None):
        with zipfile.ZipFile(archive, 'w') as wrapper:
            for name, raw, mode in members or [('release-transport.zip', inner, stat.S_IFREG | 0o600)]:
                member = zipfile.ZipInfo(name)
                member.create_system = 3
                member.external_attr = mode << 16
                wrapper.writestr(member, raw)
    write()
    return archive, inner, write


def test_exact_wrapper_exclusively_extracts_fixed_inner(sealed_wrapper, tmp_path):
    archive, inner, _ = sealed_wrapper
    output = tmp_path / 'unwrapped'
    W.unwrap_transport_artifact(archive=archive, output=output)
    assert (output / 'release-transport.zip').read_bytes() == inner
    with pytest.raises(W.P.PreparationError):
        W.unwrap_transport_artifact(archive=archive, output=output)
    assert (output / 'release-transport.zip').read_bytes() == inner


@pytest.mark.parametrize('fault', ['extra', 'duplicate', 'traversal', 'symlink', 'directory', 'changed', 'malformed', 'oversize'])
def test_wrapper_corruption_never_creates_output(sealed_wrapper, tmp_path, fault):
    archive, inner, write = sealed_wrapper
    regular = stat.S_IFREG | 0o600
    if fault == 'malformed': archive.write_bytes(b'not zip')
    elif fault == 'oversize': archive.write_bytes(b'x' * 4194305)
    elif fault == 'extra': write([('release-transport.zip', inner, regular), ('extra', b'x', regular)])
    elif fault == 'duplicate': write([('release-transport.zip', inner, regular)] * 2)
    elif fault == 'traversal': write([('../release-transport.zip', inner, regular)])
    elif fault == 'symlink': write([('release-transport.zip', inner, stat.S_IFLNK | 0o777)])
    elif fault == 'directory': write([('release-transport.zip/', inner, stat.S_IFDIR | 0o700)])
    else: write([('release-transport.zip', b'changed', regular)])
    output = tmp_path / 'refused'
    with pytest.raises(W.P.PreparationError):
        W.unwrap_transport_artifact(archive=archive, output=output)
    assert not output.exists()


@pytest.mark.parametrize('selected', ['', 'unknown'])
def test_plan_requires_explicit_known_selector(packet, tmp_path, selected):
    prepared, report_path, _, _, _ = packet
    with pytest.raises(W.P.PreparationError):
        W.prepare_uploads(prepared=prepared, report_path=report_path, output=tmp_path / 'unknown',
                          pypi_project=selected)
    assert not (tmp_path / 'unknown').exists()


def test_cli_plan_selector_must_match_admitted_scope(packet, tmp_path, monkeypatch):
    prepared, report_path, _, _, _ = packet
    for key, value in (admitted() | dict(PYPI_PROJECT='cragkit')).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv('GITHUB_OUTPUT', str(tmp_path / 'job-output'))
    result = W.main(['plan', '--prepared', str(prepared), '--report', str(report_path),
                     '--output', str(tmp_path / 'wrong-scope'), '--pypi-project', 'all'])
    assert result == 1 and not (tmp_path / 'wrong-scope').exists()


def test_cli_postflight_absence_is_pending_not_success(packet, monkeypatch):
    _, report_path, _, _, _ = packet
    assert W.main(['postflight', '--report', str(report_path), '--pypi-project', 'all']) == 2


def test_postflight_conflict_is_failure_without_private_diagnostics(packet, capsys):
    _, report_path, _, report, save = packet
    report['products'][0].update(state='error', reason='private-provider-text')
    save()
    assert W.main(['postflight', '--report', str(report_path), '--pypi-project', 'all']) == 1
    captured = capsys.readouterr()
    assert 'private-provider-text' not in captured.out + captured.err


@pytest.mark.parametrize('fault', ['encrypted', 'declared_size'])
def test_wrapper_metadata_is_rejected_before_member_read(sealed_wrapper, tmp_path, monkeypatch, fault):
    import struct
    archive, inner, _ = sealed_wrapper
    raw = bytearray(archive.read_bytes())
    central = raw.index(b'PK\x01\x02')
    if fault == 'encrypted':
        struct.pack_into('<H', raw, 6, struct.unpack_from('<H', raw, 6)[0] | 1)
        struct.pack_into('<H', raw, central + 8, struct.unpack_from('<H', raw, central + 8)[0] | 1)
    else:
        struct.pack_into('<I', raw, 22, len(inner) + 1)
        struct.pack_into('<I', raw, central + 24, len(inner) + 1)
    archive.write_bytes(raw)
    monkeypatch.setattr(zipfile.ZipFile, 'open', lambda *a, **kw: pytest.fail('invalid member read'))
    output = tmp_path / 'invalid-metadata'
    with pytest.raises(W.P.PreparationError, match='artifact_member'):
        W.unwrap_transport_artifact(archive=archive, output=output)
    assert not output.exists()
