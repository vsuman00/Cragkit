"""Verify core and optional LangChain packages, including clean installed artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable

from check_core_pipeline import PipelineFailure, Step, pipeline as core_pipeline, run_checks

ROOT = Path(__file__).resolve().parents[1]


def pipeline(root: Path, output: Path) -> tuple[Step, ...]:
    uv=('uv','run','--project','packages/langchain-python','--frozen')
    node=root/'packages/langchain-typescript'
    return core_pipeline(root,output/'core') + (
        Step('python-sdk-frozen-install',('uv','sync','--project','packages/langchain-python','--frozen'),root,300),
        Step('node-sdk-frozen-install',('npm','ci','--ignore-scripts'),node,300),
        Step('python-sdk-types',uv+('mypy','--config-file','packages/langchain-python/pyproject.toml','packages/langchain-python/src'),root,120),
        Step('python-sdk-tests',uv+('pytest','packages/langchain-python/tests','-q'),root,120),
        Step('node-sdk-types',('npm','run','typecheck'),node,120),
        Step('node-sdk-tests',('npm','test'),node,120),
        Step('clean-framework-artifacts',(sys.executable,'tools/check_framework_artifacts.py','--core-artifacts',str(output/'core'),'--output-dir',str(output/'frameworks')),root,600),
    )


def main(argv: list[str] | None = None, *, runner: Callable[..., Any] = subprocess.run) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts-dir',type=Path,default=ROOT/'artifacts/V4/acceptance')
    args=parser.parse_args(argv)
    output=args.artifacts_dir.resolve()
    try:
        count=run_checks(ROOT,output,runner,steps=pipeline(ROOT,output))
    except PipelineFailure as error:
        print(f'SDK package checks failed at stage: {error.stage}.',file=sys.stderr)
        return 1
    print(json.dumps({'state':'passed','steps':count,'artifacts_dir':str(output)}))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
