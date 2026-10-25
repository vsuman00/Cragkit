"""Synthetic checks for the explicit, rolled-back administrative security probe."""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
SPEC = importlib.util.spec_from_file_location('check_security_remnants', Path(__file__).resolve().parents[1] / 'check_security_remnants.py')
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class DatabaseError(Exception):
    sqlstate = 'P0001'
    def __init__(self, message):
        self.diag = SimpleNamespace(message_primary=message)


def test_negative_probe_requires_exact_failure_and_always_rolls_back(monkeypatch):
    connection = SimpleNamespace(execute=AsyncMock())
    execute = AsyncMock(side_effect=DatabaseError('expected fixed diagnostic'))
    monkeypatch.setattr(PROBE, 'execute_script', execute)
    assert asyncio.run(PROBE.probe(connection, 'case', 'synthetic mutation',
                                  'expected fixed diagnostic', managed=True)) == 'case'
    assert connection.execute.call_args.args == ('ROLLBACK',)
    assert execute.call_args.args[1].count('BEGIN;') == 0
    assert "security_vector_profile = 'neon-managed'" in execute.call_args.args[1]


@pytest.mark.parametrize('error', [None, DatabaseError('other error'), RuntimeError('private detail')])
def test_negative_probe_does_not_mistake_acceptance_or_other_failure_for_rejection(monkeypatch, error):
    connection = SimpleNamespace(execute=AsyncMock())
    monkeypatch.setattr(PROBE, 'execute_script', AsyncMock(side_effect=error))
    with pytest.raises(RuntimeError, match='unsafe_security_probe_accepted|unexpected_security_probe_failure'):
        asyncio.run(PROBE.probe(connection, 'case', 'synthetic mutation', 'expected', managed=False))
    assert connection.execute.call_args.args == ('ROLLBACK',)


def test_probe_cli_requires_explicit_write_and_target_flags(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['probe', '--config', '/synthetic.json'])
    with pytest.raises(SystemExit) as error:
        PROBE.main()
    assert error.value.code == 2
