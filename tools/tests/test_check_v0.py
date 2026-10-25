import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location("check_v0", Path(__file__).resolve().parents[1] / "check_v0.py")
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "packages/typescript").mkdir(parents=True)
    return tmp_path


def test_pipeline_runs_each_command_serially_with_owned_cwd_and_timeout(workspace):
    calls = []
    running = False
    def runner(command, **kwargs):
        nonlocal running
        assert not running
        running = True
        assert kwargs["cwd"].is_relative_to(workspace)
        assert kwargs["check"] is False
        assert 0 < kwargs["timeout"] <= 600
        assert "shell" not in kwargs
        calls.append((command, kwargs["cwd"]))
        running = False
        return SimpleNamespace(returncode=0)
    output = workspace / "artifacts with spaces"
    assert CHECK.run_checks(workspace, output, runner) == 21
    assert len(calls) == 21
    assert calls[0][0] == ["uv", "sync", "--project", "packages/python", "--frozen"]
    assert calls[1] == (["npm", "ci", "--ignore-scripts"], workspace / "packages/typescript")
    assert calls[-1][0][-2:] == ["--output-dir", str(output)]
    corpus = next(command for command, _ in calls if "tools/check_corpus.py" in command)
    assert "--require-human-review" in corpus
    assert "--include-held-out" not in corpus
    assert sum("--fixtures" in command for command, _ in calls) == 2
    assert any("tools/check_seal.py" in command for command, _ in calls)
    assert any("tools/check_vector_contract.py" in command for command, _ in calls)
    assert any("tools/check_identifier_fusion.py" in command for command, _ in calls)
    assert any("tools/check_hybrid_contract.py" in command for command, _ in calls)
    assert any("tools/check_reranking.py" in command for command, _ in calls)
    assert any("tools/check_context.py" in command for command, _ in calls)
    assert any("tools/check_packing.py" in command for command, _ in calls)
    assert any("tools/fetch_tokenizer.py" in command for command, _ in calls)


@pytest.mark.parametrize("failure", ["exit", "timeout", "missing-command"])
def test_failed_stage_stops_before_any_later_command(workspace, failure):
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        if len(calls) == 3:
            if failure == "timeout":
                raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="private detail")
            if failure == "missing-command":
                raise FileNotFoundError("private detail")
            return SimpleNamespace(returncode=7)
        return SimpleNamespace(returncode=0)
    with pytest.raises(CHECK.PipelineFailure, match="pinned-tokenizer-asset") as caught:
        CHECK.run_checks(workspace, workspace / "artifacts", runner)
    assert len(calls) == 3
    assert "private detail" not in str(caught.value)


def test_missing_package_cwd_does_not_launch_subprocess(tmp_path):
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)
    with pytest.raises(CHECK.PipelineFailure, match="typescript-frozen-install"):
        CHECK.run_checks(tmp_path, tmp_path / "artifacts", runner)
    assert len(calls) == 1


def test_main_reports_success_only_after_all_commands(workspace, monkeypatch, capsys):
    monkeypatch.setattr(CHECK, "ROOT", workspace)
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)
    assert CHECK.main([], runner=runner) == 0
    output = capsys.readouterr().out.splitlines()
    result = json.loads(output[-1])
    assert result == {"status": "passed", "steps": len(calls), "artifacts_dir": str(workspace / "artifacts/V0")}


def test_main_reports_failed_exit_without_success_marker(workspace, monkeypatch, capsys):
    monkeypatch.setattr(CHECK, "ROOT", workspace)
    def runner(command, **kwargs):
        return SimpleNamespace(returncode=1)
    assert CHECK.main([], runner=runner) == 1
    output = capsys.readouterr()
    assert "python-frozen-install" in output.err
    assert '"status": "passed"' not in output.out
