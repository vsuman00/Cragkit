"""Run the local V0 acceptance checks sequentially."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, NamedTuple

ROOT = Path(__file__).resolve().parents[1]


class Step(NamedTuple):
    name: str
    command: tuple[str, ...]
    cwd: Path
    timeout: int


class PipelineFailure(RuntimeError):
    def __init__(self, stage: str) -> None:
        self.stage = stage
        super().__init__(f"Local V0 checks failed at stage: {stage}.")


def pipeline(root: Path, artifacts_dir: Path) -> tuple[Step, ...]:
    uv = ("uv", "run", "--project", "packages/python", "--frozen")
    typescript = root / "packages/typescript"
    return (
        Step("python-frozen-install", ("uv", "sync", "--project", "packages/python", "--frozen"), root, 300),
        Step("typescript-frozen-install", ("npm", "ci", "--ignore-scripts"), typescript, 300),
        Step("pinned-tokenizer-asset", (sys.executable, "tools/fetch_tokenizer.py"), root, 60),
        Step("python-types", uv + ("mypy", "--config-file", "packages/python/pyproject.toml", "packages/python/src"), root, 120),
        Step("typescript-types", ("npm", "run", "typecheck"), typescript, 120),
        Step("python-tests", uv + ("pytest", "packages/python/tests", "tools/tests", "-q"), root, 120),
        Step("typescript-tests", ("npm", "test"), typescript, 120),
        Step("schema-drift", uv + ("python", "tools/export_schemas.py", "--check"), root, 60),
        Step("request-parity", uv + ("python", "tools/check_contracts.py", "--fixtures", "requests"), root, 60),
        Step("result-parity", uv + ("python", "tools/check_contracts.py", "--fixtures", "results"), root, 60),
        Step("execution-parity", uv + ("python", "tools/check_execution.py"), root, 60),
        Step("planning-parity", uv + ("python", "tools/check_planning.py"), root, 60),
        Step("embedding-parity", uv + ("python", "tools/check_embeddings.py"), root, 60),
        Step("vector-generation-parity", uv + ("python", "tools/check_vector_contract.py"), root, 60),
        Step("dense-parity", uv + ("python", "tools/check_dense_contract.py"), root, 60),
        Step("identifier-fusion-parity", uv + ("python", "tools/check_identifier_fusion.py"), root, 60),
        Step("hybrid-parity", uv + ("python", "tools/check_hybrid_contract.py"), root, 60),
        Step("reranking-parity", uv + ("python", "tools/check_reranking.py"), root, 60),
        Step("context-parity", uv + ("python", "tools/check_context.py"), root, 60),
        Step("packing-parity", uv + ("python", "tools/check_packing.py"), root, 60),
        Step("assessment-parity", uv + ("python", "tools/check_assessment.py"), root, 60),
        Step("evidence-pipeline-parity", uv + ("python", "tools/check_evidence_pipeline.py"), root, 60),
        Step("development-corpus", (sys.executable, "tools/check_corpus.py", "--require-human-review"), root, 60),
        Step("sealed-input-integrity", (sys.executable, "tools/check_seal.py"), root, 60),
        Step("clean-package-artifacts", (sys.executable, "tools/check_artifacts.py", "--output-dir", str(artifacts_dir)), root, 600),
    )


def run_checks(root: Path, artifacts_dir: Path,
               runner: Callable[..., Any] = subprocess.run) -> int:
    root = root.resolve()
    steps = pipeline(root, artifacts_dir.resolve())
    completed = 0
    for step in steps:
        cwd = step.cwd.resolve()
        if not root.is_dir() or not cwd.is_dir() or not cwd.is_relative_to(root):
            raise PipelineFailure(step.name)
        print(f"[{completed + 1}/{len(steps)}] {step.name}", flush=True)
        failed = False
        try:
            result = runner(list(step.command), cwd=cwd, timeout=step.timeout, check=False)
            failed = result.returncode != 0
        except (OSError, subprocess.TimeoutExpired):
            failed = True
        if failed:
            raise PipelineFailure(step.name) from None
        completed += 1
    return completed


def main(argv: list[str] | None = None, *, runner: Callable[..., Any] = subprocess.run) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", type=Path, default=ROOT / "artifacts/V0")
    args = parser.parse_args(argv)
    try:
        completed = run_checks(ROOT, args.artifacts_dir, runner)
    except PipelineFailure as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps({"status": "passed", "steps": completed,
                      "artifacts_dir": str(args.artifacts_dir.resolve())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
