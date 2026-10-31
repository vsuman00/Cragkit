"""A release preflight must fail closed before held-out labels are opened."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('check_release_readiness', TOOLS / 'check_release_readiness.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
ROOT = TOOLS.parent


def configuration():
    return json.loads((ROOT / 'evaluation/release/V6-candidate.json').read_text())


def test_valid_configuration_does_not_open_held_out(monkeypatch):
    original = Path.open
    def guard(path, *args, **kwargs):
        assert path.name != 'held_out.json', 'preregistration leaked held-out access'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guard)
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
