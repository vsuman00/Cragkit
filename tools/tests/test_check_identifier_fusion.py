"""Keep recursive parity checks strict and child failure details redacted."""
import importlib.util
from pathlib import Path
import sys

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location('check_identifier_fusion', TOOLS / 'check_identifier_fusion.py')
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def test_full_provenance_and_numeric_tolerance():
    CHECK.compare({'score': 1/61, 'rank': 1}, {'score': 1/61+1e-13, 'rank': 1})
    for actual in ({'score': float('nan'), 'rank': 1}, {'score': 1/61, 'rank': True}, {'score': 1/61}):
        with pytest.raises(ValueError):
            CHECK.compare(actual, {'score': 1/61, 'rank': 1})


def test_child_failures_do_not_disclose_private_details(monkeypatch, capsys):
    def fail():
        raise RuntimeError('private source or credentials')
    monkeypatch.setattr(CHECK, 'check', fail)
    assert CHECK.main() == 1
    assert 'private' not in capsys.readouterr().out
