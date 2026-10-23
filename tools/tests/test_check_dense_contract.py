"""Keep synthetic distance reference and checker failures explicit."""
import importlib.util
from pathlib import Path
import sys

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location('check_dense_contract', TOOLS / 'check_dense_contract.py')
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def test_axis_distance_reference_and_symmetry():
    assert CHECK.distance([1., 0.], [1., 0.]) == 0
    assert CHECK.distance([1., 0.], [0., 1.]) == 1
    assert CHECK.distance([1., 0.], [-1., 0.]) == 2
    assert CHECK.distance([.6, .8], [1., 0.]) == CHECK.distance([1., 0.], [.6, .8])


def test_checker_does_not_log_raw_child_failures(monkeypatch, capsys):
    async def fail():
        raise RuntimeError('private source query or credentials')
    monkeypatch.setattr(CHECK, 'check', fail)
    assert CHECK.main() == 1
    assert 'private' not in capsys.readouterr().out
