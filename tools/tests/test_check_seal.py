"""Protect the approved input inventory and held-out labels from silent drift."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location("check_seal", Path(__file__).parents[1] / "check_seal.py")
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def make_packet(root: Path) -> dict:
    files = {
        "evaluation/corpus/manifest.json": json.dumps({"documents": [{"path": "source.txt"}]}),
        "evaluation/corpus/source.txt": "Original source café 🙂\n",
        "evaluation/questions/dev.json": "Development fixture bytes\n",
        "evaluation/questions/held_out.json": "Held-out fixture bytes, deliberately not parsed\n",
        "evaluation/review/V0-labels.md": "Approved packet\n",
    }
    record = {
        "schema_version": "0.1", "state": "sealed",
        "human_review": {
            "state": "approved", "reviewer": "test-reviewer", "reviewed_on": "2026-10-19",
            "decision": "Approved fixture", "source": "Explicit test review",
        },
        "exposure": "Initial fixture author reviewed the held-out packet.",
        "files": [],
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        record["files"].append({"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    (root / "evaluation/review/seal.json").write_text(json.dumps(record))
    return record


def test_complete_inventory_passes_without_parsing_held_out_labels(tmp_path):
    make_packet(tmp_path)
    assert checker.validate_seal(tmp_path) == {"state": "sealed", "files": 5}


@pytest.mark.parametrize("name", ["evaluation/corpus/source.txt", "evaluation/questions/held_out.json"])
def test_changed_source_or_held_out_labels_fail(tmp_path, name):
    make_packet(tmp_path)
    (tmp_path / name).write_text("Changed input")
    with pytest.raises(checker.SealError, match="sealed_input_changed"):
        checker.validate_seal(tmp_path)


@pytest.mark.parametrize("change,code", [
    (lambda record: record["files"].pop(), "incomplete_inventory"),
    (lambda record: record["files"].append(copy.deepcopy(record["files"][0])), "file_inventory"),
    (lambda record: record["human_review"].update(state="pending"), "human_review_pending"),
    (lambda record: record["files"][0].update(path="../outside"), "file_inventory"),
])
def test_inventory_and_review_cannot_be_silently_weakened(tmp_path, change, code):
    record = make_packet(tmp_path)
    change(record)
    (tmp_path / "evaluation/review/seal.json").write_text(json.dumps(record))
    with pytest.raises(checker.SealError, match=code):
        checker.validate_seal(tmp_path)
