"""Keep contract-checker failures redacted."""
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('check_reranking', Path(__file__).resolve().parents[1]/'check_reranking.py')
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def test_failure_is_redacted(monkeypatch, capsys):
    async def fail():
        raise RuntimeError('private query and credential')
    monkeypatch.setattr(CHECK, 'check', fail)
    assert CHECK.main() == 1
    assert 'private' not in capsys.readouterr().out
