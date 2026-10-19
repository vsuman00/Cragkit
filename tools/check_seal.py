"""Verify approved corpus inputs without interpreting held-out question labels."""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


class SealError(ValueError):
    """A stable integrity code, without source or query text."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise SealError(code)


def read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise SealError("unreadable_record") from None
    require(type(value) is dict, "record_shape")
    return value


def validate_seal(root: Path) -> dict[str, int | str]:
    root = root.resolve()
    record = read_object(root / "evaluation/review/seal.json")
    require(set(record) == {"schema_version", "state", "human_review", "exposure", "files"}, "seal_shape")
    require(record["schema_version"] == "0.1" and record["state"] == "sealed", "seal_state")
    review = record["human_review"]
    require(type(review) is dict and set(review) == {
        "state", "reviewer", "reviewed_on", "decision", "source",
    }, "review_shape")
    require(review["state"] == "approved", "human_review_pending")
    require(all(type(review[key]) is str and bool(review[key].strip()) for key in (
        "reviewer", "reviewed_on", "decision", "source",
    )), "review_metadata")
    try:
        date.fromisoformat(review["reviewed_on"])
    except ValueError:
        raise SealError("review_date") from None
    require(type(record["exposure"]) is str and bool(record["exposure"].strip()), "exposure_disclosure")
    manifest = read_object(root / "evaluation/corpus/manifest.json")
    require(type(manifest.get("documents")) is list, "manifest_documents")
    expected = {
        "evaluation/corpus/manifest.json", "evaluation/questions/dev.json",
        "evaluation/questions/held_out.json", "evaluation/review/V0-labels.md",
    }
    for document in manifest["documents"]:
        require(type(document) is dict and type(document.get("path")) is str, "source_path")
        source = Path("evaluation/corpus") / document["path"]
        require(not Path(document["path"]).is_absolute() and ".." not in source.parts, "source_path")
        expected.add(source.as_posix())
    require(type(record["files"]) is list, "seal_files")
    seen: set[str] = set()
    for item in record["files"]:
        require(type(item) is dict and set(item) == {"path", "sha256"}, "file_record")
        name, digest = item["path"], item["sha256"]
        require(type(name) is str and name in expected and name not in seen, "file_inventory")
        require(type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest) is not None, "file_digest")
        path = (root / name).resolve()
        require(path.is_relative_to(root), "file_path")
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            raise SealError("missing_sealed_file") from None
        require(actual == digest, "sealed_input_changed")
        seen.add(name)
    require(seen == expected, "incomplete_inventory")
    return {"state": "sealed", "files": len(seen)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        result = validate_seal(args.root)
    except SealError as error:
        print(f"Seal validation failed: {error}")
        return 1
    except (TypeError, KeyError, ValueError):
        print("Seal validation failed: malformed_record")
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
