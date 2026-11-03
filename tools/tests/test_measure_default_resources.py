"""RST-r1 rejects unusable timing evidence and sustained pressure."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import measure_default_resources as R


@pytest.mark.parametrize('samples', [[], [True], [0], [-1], [float('nan')], [float('inf')], ['1']])
def test_invalid_sample_is_never_a_fast_pass(samples):
    with pytest.raises(R.ResourceCheckError):
        R.distribution(samples)


def test_small_sample_p95_is_maximum_not_interpolation():
    assert R.distribution([5, 1, 3, 2, 4]) == dict(count=5, median=3, p95=5, maximum=5)


@pytest.mark.parametrize('mutation', ['missing', 'extra', 'warm_count', 'rss', 'nan'])
def test_probe_requires_both_bounded_complete_observations(mutation):
    fresh = dict(import_seconds=.1, peak_rss_bytes=1234)
    warm = dict(warm_seconds=[.001]*50, peak_rss_bytes=2345)
    if mutation == 'warm_count':
        warm['warm_seconds'].pop()
    if mutation == 'rss':
        fresh['peak_rss_bytes'] = True
    if mutation == 'nan':
        fresh['import_seconds'] = float('nan')
    lines = [json.dumps(fresh), json.dumps(warm)]
    if mutation == 'missing':
        lines.pop()
    if mutation == 'extra':
        lines.append('{}')
    with pytest.raises(R.ResourceCheckError):
        R.parse_probe('\n'.join(lines))


def test_two_growing_swap_intervals_stop_before_next_work(monkeypatch):
    records = [dict(free_percent=50, swapout_pages=1), dict(free_percent=50, swapout_pages=2)]
    monkeypatch.setattr(R, 'pressure', lambda: dict(free_percent=50, swapout_pages=3))
    with pytest.raises(R.ResourceCheckError, match='resource_swapping_stop'):
        R.pressure_guard(records)
    assert len(records) == 2


def test_one_historical_swap_change_does_not_imply_sustained_growth(monkeypatch):
    records = [dict(free_percent=50, swapout_pages=1), dict(free_percent=50, swapout_pages=2)]
    monkeypatch.setattr(R, 'pressure', lambda: dict(free_percent=50, swapout_pages=2))
    R.pressure_guard(records)
    assert len(records) == 3
