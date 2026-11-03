"""A release preflight must fail closed before held-out labels are opened."""
from copy import deepcopy
import importlib.util
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from dataclasses import replace

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location('check_release_readiness', TOOLS / 'check_release_readiness.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
ROOT = TOOLS.parent


def configuration():
    return json.loads((ROOT / 'evaluation/release/V6-candidate.json').read_text())


def test_valid_configuration_does_not_open_held_out(monkeypatch):
    original = Path.open
    descriptor_open = os.open
    def guard(path, *args, **kwargs):
        assert path.name != 'held_out.json', 'preregistration leaked held-out access'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guard)
    def descriptor_guard(path, *args, **kwargs):
        assert Path(path).name != 'held_out.json', 'preregistration leaked held-out access'
        return descriptor_open(path, *args, **kwargs)
    monkeypatch.setattr(os, 'open', descriptor_guard)
    result = CHECK.check_configuration(ROOT, configuration())
    assert result['state'] == 'configuration_verified' and result['held_out_opened'] is False
    assert result['release_readiness'] == 'not_proven_by_preregistration'


@pytest.mark.parametrize('field,value,code', [
    ('configuration_state', 'draft', 'unfrozen_configuration'),
    ('license', {'spdx': None}, 'unresolved_license'),
    ('inputs', {}, 'missing_frozen_inputs'),
    ('held_out', {'path': 'evaluation/questions/held_out.json', 'current_run_access': 'scored'}, 'held_out_access_not_preregistered'),
])
def test_incomplete_or_leaked_candidate_is_not_accepted(field, value, code):
    candidate = configuration(); candidate[field] = value
    with pytest.raises(CHECK.ReleaseConfigurationError, match=code):
        CHECK.check_configuration(ROOT, candidate)


def test_changed_policy_and_weakened_invariants_refused():
    candidate = configuration(); candidate['inputs']['evaluation/runners/benchmark_metrics.py'] = '0'*64
    with pytest.raises(CHECK.ReleaseConfigurationError, match='frozen_input_drift'):
        CHECK.check_configuration(ROOT, candidate)
    candidate = configuration(); candidate['quality_targets']['false_sufficient_count'] = 1
    with pytest.raises(CHECK.ReleaseConfigurationError, match='weakened_invariant_target'):
        CHECK.check_configuration(ROOT, candidate)


def test_frozen_deadline_and_paid_call_limits_cannot_expand():
    for field in ('request_limits', 'live_limits'):
        candidate = deepcopy(configuration())
        candidate[field]['concurrency'] = 2
        with pytest.raises(CHECK.ReleaseConfigurationError, match='unfrozen_.*limits'):
            CHECK.check_configuration(ROOT, candidate)


def synthetic_packet_tree(tmp_path, monkeypatch, revision='original-r1'):
    """No real held-out labels: files carry only synthetic metadata/digests."""
    candidate = configuration()
    candidate['evaluation_revision'] = revision
    candidate['held_out'] = {'path': CHECK.packet_profile(candidate).question_path,
        'sha256': ('b' if revision == 'recovery-r1' else 'a') * 64,
        'current_run_access': 'not_opened_or_scored'}
    pins = {}
    def write(name, value):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(value, sort_keys=True).encode()
        path.write_bytes(raw)
        return sha256(raw).hexdigest()
    limits = CHECK.input_limits(candidate)
    candidate['inputs'] = {name: write(name, {'synthetic': name}) for name in limits}
    original_files = [{'path': name, 'sha256': candidate['inputs'][name]} for name in
        ('evaluation/corpus/manifest.json', 'evaluation/questions/dev.json')]
    original_files.append({'path': 'evaluation/questions/held_out.json', 'sha256': 'a' * 64})
    def seal(files):
        return {'state': 'sealed', 'human_review': {'state': 'approved', 'reviewer': 'synthetic-reviewer'},
            'files': files}
    original = seal(original_files)
    original_path = 'evaluation/review/seal.json'
    candidate['inputs'][original_path] = write(original_path, original)
    pins['original'] = candidate['inputs'][original_path]
    monkeypatch.setattr(CHECK, 'APPROVED_SEAL_SHA256', pins['original'])
    selected = CHECK.packet_profile(candidate)
    recovery = None
    if revision == 'recovery-r1':
        recovery = seal([{'path': selected.manifest_path, 'sha256': candidate['inputs'][selected.manifest_path]},
            {'path': selected.question_path, 'sha256': 'b' * 64}])
        candidate['inputs'][selected.seal_path] = write(selected.seal_path, recovery)
        pins['recovery'] = candidate['inputs'][selected.seal_path]
    actual_profile = CHECK.packet_profile
    def profile(config, *, split='held_out'):
        value = actual_profile(config, split=split)
        return replace(value, seal_sha256=pins['recovery']) if value.revision == 'recovery-r1' else value
    monkeypatch.setattr(CHECK, 'packet_profile', profile)
    edges = tmp_path / 'tasks/EDGE_CASES.md'
    edges.parent.mkdir(parents=True, exist_ok=True)
    edges.write_text('| E1 | synthetic case |\n')
    coverage = {'requirements': [{'id': f'BR-{i:02}', 'owner': 'synthetic',
        'state': 'pending', 'limitations': 'synthetic only', 'evidence': []} for i in range(1, 11)],
        'edge_cases': [{'id': 'E1', 'owner': 'synthetic', 'state': 'pending',
            'limitations': 'synthetic only', 'evidence': []}]}
    write('evaluation/release/V6-coverage.json', coverage)
    return candidate, original, recovery, pins, write


@pytest.mark.parametrize('revision', [None, 'original-r1', 'recovery-r1'])
def test_known_profiles_validate_without_reading_any_heldout_labels(tmp_path, monkeypatch, revision):
    candidate, *_ = synthetic_packet_tree(tmp_path, monkeypatch, revision or 'original-r1')
    if revision is None:
        del candidate['evaluation_revision']
    original_open, original_descriptor_open = Path.open, os.open
    def guard(path, *args, **kwargs):
        assert path.name != 'held_out.json'
        return original_open(path, *args, **kwargs)
    def descriptor_guard(path, *args, **kwargs):
        assert Path(path).name != 'held_out.json'
        return original_descriptor_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guard)
    monkeypatch.setattr(os, 'open', descriptor_guard)
    result = CHECK.check_configuration(tmp_path, candidate)
    assert result['held_out_opened'] is False
    assert result['input_digests'] == (8 if revision == 'recovery-r1' else 6)


@pytest.mark.parametrize('revision', [None, True, 1, [], {}, 'unknown', '../recovery-r1'])
def test_unknown_or_malformed_profile_fails_closed(revision):
    candidate = configuration()
    candidate['evaluation_revision'] = revision
    with pytest.raises(CHECK.ReleaseConfigurationError, match='^release_configuration_invalid$') as error:
        CHECK.check_settings(candidate)
    assert error.value.__context__ is None


@pytest.mark.parametrize('revision', ['original-r1', 'recovery-r1'])
@pytest.mark.parametrize('mutation', ['missing', 'extra', 'heldout'])
def test_profile_inputs_are_exact_not_caller_extensible(tmp_path, monkeypatch, revision, mutation):
    candidate, *_ = synthetic_packet_tree(tmp_path, monkeypatch, revision)
    if mutation == 'missing':
        del candidate['inputs']['evaluation/questions/dev.json']
    else:
        candidate['inputs']['arbitrary.json' if mutation == 'extra' else candidate['held_out']['path']] = '0' * 64
    with pytest.raises(CHECK.ReleaseConfigurationError, match='^missing_frozen_inputs$'):
        CHECK.check_configuration(tmp_path, candidate)


@pytest.mark.parametrize('which', ['original', 'recovery'])
def test_mutable_replacement_seal_and_matching_config_cannot_replace_source_pin(tmp_path, monkeypatch, which):
    candidate, original, recovery, pins, write = synthetic_packet_tree(tmp_path, monkeypatch, 'recovery-r1')
    path = 'evaluation/review/seal.json' if which == 'original' else CHECK.packet_profile(candidate).seal_path
    seal = original if which == 'original' else recovery
    seal['replacement'] = True
    candidate['inputs'][path] = write(path, seal)
    with pytest.raises(CHECK.ReleaseConfigurationError, match='^review_seal_drift$'):
        CHECK.check_configuration(tmp_path, candidate)


@pytest.mark.parametrize('which', ['original', 'recovery'])
@pytest.mark.parametrize('mutation', ['pending', 'missing_reviewer', 'unsealed'])
def test_even_pinned_synthetic_seals_require_approval(tmp_path, monkeypatch, which, mutation):
    candidate, original, recovery, pins, write = synthetic_packet_tree(tmp_path, monkeypatch, 'recovery-r1')
    seal = original if which == 'original' else recovery
    if mutation == 'pending':
        seal['human_review']['state'] = 'pending'
    elif mutation == 'missing_reviewer':
        seal['human_review']['reviewer'] = None
    else:
        seal['state'] = 'draft'
    path = 'evaluation/review/seal.json' if which == 'original' else CHECK.packet_profile(candidate).seal_path
    pins[which] = candidate['inputs'][path] = write(path, seal)
    if which == 'original':
        monkeypatch.setattr(CHECK, 'APPROVED_SEAL_SHA256', pins[which])
    with pytest.raises(CHECK.ReleaseConfigurationError, match='^review_not_approved$'):
        CHECK.check_configuration(tmp_path, candidate)


@pytest.mark.parametrize('mutation', ['manifest', 'heldout_digest', 'heldout_path', 'seal_duplicate'])
def test_selected_profile_manifest_and_label_metadata_cannot_swap(tmp_path, monkeypatch, mutation):
    candidate, original, recovery, pins, write = synthetic_packet_tree(tmp_path, monkeypatch, 'recovery-r1')
    profile = CHECK.packet_profile(candidate)
    if mutation == 'manifest':
        candidate['inputs'][profile.manifest_path] = write(profile.manifest_path, {'changed': True})
    elif mutation == 'heldout_digest':
        candidate['held_out']['sha256'] = 'c' * 64
    elif mutation == 'heldout_path':
        candidate['held_out']['path'] = 'evaluation/questions/held_out.json'
    else:
        recovery['files'].append(deepcopy(recovery['files'][-1]))
        pins['recovery'] = candidate['inputs'][profile.seal_path] = write(profile.seal_path, recovery)
    code = 'held_out_access_not_preregistered' if mutation == 'heldout_path' else 'held_out_seal_mismatch'
    with pytest.raises(CHECK.ReleaseConfigurationError, match='^' + code + '$'):
        CHECK.check_configuration(tmp_path, candidate)


@pytest.mark.parametrize('mutation', ['oversize', 'symlink_file', 'symlink_directory'])
def test_preregistration_inputs_are_bounded_regular_nonsymlink_files(tmp_path, monkeypatch, mutation):
    candidate, *_ = synthetic_packet_tree(tmp_path, monkeypatch)
    path = tmp_path / 'evaluation/corpus/manifest.json'
    if mutation == 'oversize':
        path.write_bytes(b'x' * 131073)
    elif mutation == 'symlink_file':
        target = tmp_path / 'copy.json'
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
    else:
        directory = path.parent
        target = tmp_path / 'corpus-copy'
        directory.rename(target)
        directory.symlink_to(target, target_is_directory=True)
    code = 'invalid_input_size' if mutation == 'oversize' else 'unsafe_input_path'
    with pytest.raises(CHECK.ReleaseConfigurationError, match='^' + code + '$'):
        CHECK.check_configuration(tmp_path, candidate)
