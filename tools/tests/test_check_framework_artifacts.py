"""The optional artifact coordinator records failures without captured secrets."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest


@pytest.fixture
def checker(monkeypatch):
    directory=Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(directory))
    spec=importlib.util.spec_from_file_location('framework_artifacts',directory/'check_framework_artifacts.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_failure_records_only_fixed_error_type(checker,monkeypatch,tmp_path,capsys):
    def failure(*args):
        raise RuntimeError('credential-and-source-canary')
    monkeypatch.setattr(checker,'python_adapter',failure)
    output=tmp_path/'out'
    assert checker.main(['--core-artifacts',str(tmp_path/'core'),'--output-dir',str(output)])==1
    text=(output/'acceptance.json').read_text()
    assert json.loads(text)['error']=='RuntimeError'
    assert 'credential-and-source-canary' not in text+capsys.readouterr().out


def test_both_native_optional_checks_required_for_success(checker,monkeypatch,tmp_path):
    calls=[]
    def passed(*args):
        calls.append(args)
        return {'state':'passed'}
    monkeypatch.setattr(checker,'python_adapter',passed)
    monkeypatch.setattr(checker,'node_adapter',passed)
    output=tmp_path/'out'
    assert checker.main(['--core-artifacts',str(tmp_path/'core'),'--output-dir',str(output)])==0
    result=json.loads((output/'acceptance.json').read_text())
    assert len(calls)==2 and result['python']['state']==result['node']['state']=='passed'
    assert calls[0][2].name.endswith('.whl') and calls[1][2].name.endswith('.tgz')
