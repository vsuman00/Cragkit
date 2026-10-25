import hashlib
import importlib.util
from pathlib import Path

import pytest

SPEC=importlib.util.spec_from_file_location('fetch_tokenizer',Path(__file__).resolve().parents[1]/'fetch_tokenizer.py')
FETCH=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FETCH)


def test_verified_cache_requires_no_network(tmp_path,monkeypatch):
    target=tmp_path/'table';target.write_bytes(b'unit fixture')
    monkeypatch.setattr(FETCH,'TARGET',target)
    monkeypatch.setattr(FETCH,'SHA256',hashlib.sha256(target.read_bytes()).hexdigest())
    def forbidden(*args,**kwargs):pytest.fail('cached tokenizer must not contact network')
    monkeypatch.setattr(FETCH.urllib.request,'urlopen',forbidden)
    assert FETCH.acquire()['source']=='verified_cache'


def test_corrupt_cache_is_not_silently_replaced(tmp_path,monkeypatch):
    target=tmp_path/'table';target.write_bytes(b'corrupt')
    monkeypatch.setattr(FETCH,'TARGET',target)
    with pytest.raises(ValueError):FETCH.acquire()
    assert target.read_bytes()==b'corrupt'


def test_failure_is_redacted(monkeypatch,capsys):
    def fail():raise RuntimeError('private details')
    monkeypatch.setattr(FETCH,'acquire',fail)
    assert FETCH.main()==1
    assert 'private' not in capsys.readouterr().out
