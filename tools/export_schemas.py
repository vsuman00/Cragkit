"""Export structural JSON Schemas, or check the committed copies for drift."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cragkit import contracts


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    models = {
        "request": contracts.RetrievalRequest,
        "tool-request": contracts.ToolRequest,
        "scope": contracts.TrustedScope,
    }
    if hasattr(contracts, "RetrievalResult"):
        models["result"] = contracts.RetrievalResult
    for name, model in models.items():
        path = ROOT / "contracts" / "schemas" / "0.1" / f"{name}.schema.json"
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        content = json.dumps(schema, indent=2, ensure_ascii=True, sort_keys=True) + "\n"
        if args.check:
            if not path.exists() or path.read_text() != content:
                raise SystemExit(f"Schema drift: {path.relative_to(ROOT)}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        print(f"{'Checked' if args.check else 'Exported'} {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
