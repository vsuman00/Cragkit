"""Redacted conformance failures and label-blind encoder invariants."""
import asyncio
import importlib.util
import math
from pathlib import Path
import sys

TOOLS=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOLS))
SPEC=importlib.util.spec_from_file_location('check_hybrid_contract',TOOLS/'check_hybrid_contract.py')
assert SPEC and SPEC.loader
CHECK=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def test_encoder_is_deterministic_bounded_normalized_and_label_blind():
    for text in CHECK.TEXTS:
        vector=CHECK.encode(text)
        assert len(vector)==1536 and vector==CHECK.encode(text)
        assert all(math.isfinite(value) for value in vector)
        assert abs(sum(value*value for value in vector)-1)<1e-12
    assert CHECK.encode('word word')==CHECK.encode('word')
    assert CHECK.encode('OTHER other')==CHECK.encode('other')


def test_probe_rejects_before_provider_or_database_when_budgets_are_too_small():
    result=asyncio.run(CHECK.probe(dict(mode='hybrid',max_candidates=1)))
    assert result==dict(error='invalid_request',calls=[])


def test_checker_never_discloses_child_or_provider_errors(monkeypatch,capsys):
    async def fail(): raise RuntimeError('private credentials and query text')
    monkeypatch.setattr(CHECK,'check',fail)
    assert CHECK.main()==1
    output=capsys.readouterr().out
    assert 'private' not in output and 'hybrid_contract_failed' in output
