"""Compare native runtime validation and normalized wire values on shared fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]

PYTHON_RUNNER = """
import json, sys
from cragkit import contracts
from cragkit.errors import CragkitError
helpers = {'request': contracts.parse_request, 'tool': contracts.parse_tool_request,
           'scope': contracts.parse_scope}
if hasattr(contracts, 'parse_result'):
    helpers['result'] = contracts.parse_result
records = []
for case in json.load(sys.stdin)['cases']:
    try:
        model = helpers[case['kind']](case['input'])
        record = {'id': case['id'], 'valid': True, 'value': model.model_dump(mode='json')}
    except CragkitError as error:
        record = {'id': case['id'], 'valid': False, 'error': error.to_dict()}
    records.append(record)
json.dump(records, sys.stdout, ensure_ascii=True, allow_nan=False)
"""


def run_runtime(command: list[str], fixture: str) -> list[dict[str, object]]:
    process = subprocess.run(
        command,
        cwd=ROOT,
        input=fixture,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(process.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", choices=("requests", "results"), default="requests")
    args = parser.parse_args()
    fixture_path = ROOT / "contracts" / "fixtures" / f"{args.fixtures}.json"
    fixture = fixture_path.read_text()
    cases = json.loads(fixture)["cases"]
    entry = (ROOT / "packages/typescript/dist/contracts.js").as_uri()
    node_runner = f"""
import * as contracts from {json.dumps(entry)};
import fs from 'node:fs';
const helpers = {{request: contracts.parse_request, tool: contracts.parse_tool_request,
                  scope: contracts.parse_scope, result: contracts.parse_result}};
const records = JSON.parse(fs.readFileSync(0, 'utf8')).cases.map((item) => {{
  try {{
    return {{id: item.id, valid: true, value: helpers[item.kind](item.input)}};
  }} catch (error) {{
    if (typeof error.to_dict !== 'function') throw error;
    return {{id: item.id, valid: false, error: error.to_dict()}};
  }}
}});
process.stdout.write(JSON.stringify(records));
"""
    python_records = run_runtime([sys.executable, "-c", PYTHON_RUNNER], fixture)
    node_records = run_runtime(["node", "--input-type=module", "-e", node_runner], fixture)
    if len(python_records) != len(cases) or len(node_records) != len(cases):
        raise SystemExit("A runtime omitted fixture outcomes")
    for case, python, node in zip(cases, python_records, node_records, strict=True):
        if python != node:
            raise SystemExit(f"Native wire mismatch for {case['id']}:\nPython: {python}\nNode: {node}")
        if python["id"] != case["id"] or python["valid"] != case["valid"]:
            raise SystemExit(f"Incorrect fixture outcome: {case['id']}")
        if case.get("expected") is not None and python.get("value") != case["expected"]:
            raise SystemExit(f"Incorrect normalized value: {case['id']}")
    print(json.dumps({
        "fixtures": args.fixtures,
        "cases": len(cases),
        "native_parity": "passed",
        "fixture_sha256": hashlib.sha256(fixture.encode()).hexdigest(),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
