"""Credential and probe checks use fake keys and never contact Cohere."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import stat

import pytest


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1]/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SAVE = load('save_cohere_key')
PROBE = load('check_cohere_reranking')
FAKE = 'UNIT_TEST_TOKEN_NOT_A_REAL_CREDENTIAL'


@pytest.fixture
def private(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    directory = tmp_path / '.config/cragkit/cohere'
    directory.mkdir(parents=True, mode=0o700)
    return directory


def test_save_and_read_owner_only_key_and_replace_atomically(private):
    SAVE.save_key(FAKE, private)
    assert PROBE.read_key() == FAKE
    assert stat.S_IMODE((private/'api-key').stat().st_mode) == 0o600
    SAVE.save_key(FAKE+'_REPLACED', private)
    assert PROBE.read_key() == FAKE+'_REPLACED'
    assert list(private.iterdir()) == [private/'api-key']


@pytest.mark.parametrize('key', ['', 'short', 'Bearer '+FAKE, '"'+FAKE+'"', FAKE+'\nextra', 'é'*25])
def test_invalid_input_preserves_existing_key(private, key):
    SAVE.save_key(FAKE, private)
    with pytest.raises(ValueError):
        SAVE.save_key(key, private)
    assert PROBE.read_key() == FAKE


@pytest.mark.parametrize('kind', ['public_file', 'public_directory', 'symlink', 'oversize'])
def test_reader_rejects_unsafe_credentials(private, kind):
    SAVE.save_key(FAKE, private)
    key = private/'api-key'
    if kind == 'public_file': key.chmod(0o644)
    if kind == 'public_directory': private.chmod(0o755)
    if kind == 'symlink':
        key.unlink()
        key.symlink_to(private.parent/'missing')
    if kind == 'oversize': key.write_text('X'*4097)
    with pytest.raises((PROBE.ProbeFailure, OSError)):
        PROBE.read_key()


def test_failed_http_observation_is_sanitized_and_not_retried(monkeypatch):
    calls = []
    monkeypatch.setattr(PROBE, 'read_key', lambda: FAKE)
    def reject(body, key, timeout, observation):
        calls.append(1)
        observation.update(http_status=401, provider_calls=1)
        raise PROBE.ProbeFailure('provider_http_status')
    monkeypatch.setattr(PROBE, 'request', reject)
    result = asyncio.run(PROBE.check())
    assert result['state'] == 'failed' and result['http_status'] == 401
    assert result['provider_calls'] == 1 and calls == [1]
    assert FAKE not in json.dumps(result)


def test_hidden_prompt_error_does_not_print_key(monkeypatch, capsys):
    monkeypatch.setattr(SAVE.getpass, 'getpass', lambda prompt: FAKE)
    def fail(*args): raise RuntimeError(FAKE)
    monkeypatch.setattr(SAVE, 'save_key', fail)
    assert SAVE.main() == 1
    assert FAKE not in capsys.readouterr().out


def test_node_refuses_without_live_opt_in_before_credentials_or_network():
    import subprocess
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(['node', 'tools/check_typescript_cohere_reranking.mjs'],
                            cwd=root, capture_output=True, text=True, timeout=10)
    report = json.loads(result.stdout)
    assert result.returncode == 1
    assert report['error_code'] == 'live_opt_in_required'
    assert report['provider_calls'] == 0 and report['http_status'] is None


def test_maximum_key_roundtrips_without_newline_overflow(private):
    SAVE.save_key('X'*4096, private)
    assert PROBE.read_key() == 'X'*4096
    assert (private/'api-key').stat().st_size == 4096


def test_hidden_prompt_refuses_echo_fallback(monkeypatch, capsys):
    import warnings
    saved = []
    def fallback(prompt):
        warnings.warn('echo would be enabled', SAVE.getpass.GetPassWarning)
        return FAKE
    monkeypatch.setattr(SAVE.getpass, 'getpass', fallback)
    monkeypatch.setattr(SAVE, 'save_key', lambda *args: saved.append(args))
    assert SAVE.main() == 1
    assert saved == [] and FAKE not in capsys.readouterr().out


@pytest.mark.parametrize('prefix', ['sk-proj-', 'sk-svcacct-'])
def test_recognizable_wrong_provider_keys_never_dispatch(private, monkeypatch, prefix):
    SAVE.save_key(FAKE, private)
    with pytest.raises(ValueError):
        SAVE.save_key(prefix+FAKE, private)
    assert PROBE.read_key() == FAKE
    (private/'api-key').write_text(prefix+FAKE)
    def forbidden(*args):
        pytest.fail('A wrong-provider key must never be dispatched')
    monkeypatch.setattr(PROBE, 'request', forbidden)
    report = asyncio.run(PROBE.check())
    assert report['error_code'] == 'credential_provider_mismatch'
    assert report['provider_calls'] == 0
    assert FAKE not in json.dumps(report)
