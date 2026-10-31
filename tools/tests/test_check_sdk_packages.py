"""V4 acceptance includes optional packages after the core checkpoint."""
import importlib.util
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def checker(monkeypatch):
    directory=Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(directory))
    spec=importlib.util.spec_from_file_location('check_sdk_packages',directory/'check_sdk_packages.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v4_serial_order_and_sdk_artifact_dependency(checker,tmp_path):
    steps=checker.pipeline(checker.ROOT,tmp_path)
    assert len(steps)==34
    assert steps[26].name=='clean-package-artifacts'
    assert steps[-1].name=='clean-framework-artifacts'
    assert str(tmp_path/'core') in steps[-1].command
    assert all(step.timeout<=600 for step in steps)
    calls=[]
    def runner(command,**kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command,0)
    assert checker.main(['--artifacts-dir',str(tmp_path)],runner=runner)==0
    assert len(calls)==34


def test_v4_stops_at_first_failure(checker,tmp_path,capsys):
    calls=[]
    def runner(command,**kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command,1)
    assert checker.main(['--artifacts-dir',str(tmp_path)],runner=runner)==1
    assert len(calls)==1 and 'python-frozen-install' in capsys.readouterr().err
