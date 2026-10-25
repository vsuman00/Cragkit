"""Regression for mandatory privilege restoration after an unrelated cleanup error."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

SPEC = importlib.util.spec_from_file_location('check_dense_cleanup', Path(__file__).resolve().parents[1] / 'check_dense.py')
assert SPEC and SPEC.loader
DENSE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DENSE)


def test_vector_create_revoked_even_when_other_cleanup_fails(monkeypatch):
    monkeypatch.setattr(DENSE.asyncio, 'create_subprocess_exec', AsyncMock(side_effect=RuntimeError('synthetic spawn failure')))
    actions = []
    async def mutate(action, enabled):
        actions.append((action, enabled))
        if action == 'revoke':
            raise RuntimeError('synthetic restore failure')
    config = SimpleNamespace(model_dump=lambda **kwargs: {})
    with pytest.raises(RuntimeError, match='synthetic restore failure'):
        asyncio.run(DENSE.run_node(config, {}, mutate))
    assert actions == [('revoke', False), ('vector_create', False)]
