import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("check_corpus", Path(__file__).resolve().parents[1] / "check_corpus.py")
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def packet(tmp_path):
    corpus = tmp_path / "evaluation/corpus"
    corpus.mkdir(parents=True)
    source = "Café 🙂 retry.\n".encode("utf-8")
    documents = []
    datasets = []
    for split, name in (("development", "dev"), ("held_out", "held")):
        path = f"{name}.txt"
        (corpus / path).write_bytes(source)
        digest = hashlib.sha256(source).hexdigest()
        documents.append({"tenant_id": "tenant-a", "collection": "docs", "document_id": name,
                          "revision_id": "r1", "family_id": name, "split": split, "active": True,
                          "path": path, "canonical_sha256": digest})
        support = {"document_id": name, "revision_id": "r1", "start_byte": 0,
                   "end_byte": len(source), "text": source.decode(), "canonical_sha256": digest}
        question = {"question_id": f"q-{name}", "tenant_id": "tenant-a", "collection": "docs",
                    "query": "How to retry?", "required_filters": [], "answerability": "answerable",
                    "facets": [{"facet_id": f"f-{name}", "question": "How?", "state": "supported", "support": [support]}]}
        datasets.append({"schema_version": "0.1", "origin": "synthetic", "human_review": {"state": "pending", "reviewer": None}, "questions": [question]})
    manifest = {"schema_version": "0.1", "documents": documents}
    write(corpus / "manifest.json", manifest)
    write(tmp_path / "evaluation/questions/dev.json", datasets[0])
    write(tmp_path / "evaluation/questions/held_out.json", datasets[1])
    return tmp_path, manifest, datasets


def persist(packet):
    root, manifest, datasets = packet
    write(root / "evaluation/corpus/manifest.json", manifest)
    write(root / "evaluation/questions/dev.json", datasets[0])
    write(root / "evaluation/questions/held_out.json", datasets[1])


def test_valid_packet_counts_and_explicit_initial_held_out_review(packet):
    root, _, _ = packet
    default = CHECK.validate_corpus(root)
    assert default["documents"] == 2
    assert default["questions"] == default["support_spans"] == 1
    assert default["human_review_pending"] == 1
    full = CHECK.validate_corpus(root, include_held_out=True)
    assert full["questions"] == full["human_review_pending"] == 2


def test_default_never_opens_held_out_labels(packet, monkeypatch):
    root, _, _ = packet
    original = Path.read_text
    def guarded(path, *args, **kwargs):
        if path.name == "held_out.json":
            raise AssertionError("Held-out labels were opened")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", guarded)
    assert CHECK.validate_corpus(root)["questions"] == 1
    with pytest.raises(AssertionError, match="Held-out"):
        CHECK.validate_corpus(root, include_held_out=True)


@pytest.mark.parametrize("mutation", ["offset", "support_digest", "foreign_scope", "family_leak", "duplicate_question", "duplicate_document", "source_digest", "inactive", "filter", "duplicate_reference"])
def test_mechanical_mutations_are_rejected(packet, mutation):
    root, manifest, datasets = packet
    question = datasets[0]["questions"][0]
    support = question["facets"][0]["support"][0]
    if mutation == "offset": support["start_byte"] = 4
    elif mutation == "support_digest": support["canonical_sha256"] = "0" * 64
    elif mutation == "foreign_scope": question["tenant_id"] = "tenant-b"
    elif mutation == "family_leak": manifest["documents"][1]["family_id"] = "dev"
    elif mutation == "duplicate_question": datasets[0]["questions"].append(question)
    elif mutation == "duplicate_document": manifest["documents"].append(manifest["documents"][0])
    elif mutation == "source_digest": (root / "evaluation/corpus/dev.txt").write_bytes(b"changed")
    elif mutation == "inactive": manifest["documents"][0]["active"] = False
    elif mutation == "filter": question["required_filters"] = [{"op": "eq", "field": "document_id", "value": "other"}]
    elif mutation == "duplicate_reference": question["facets"][0]["support"].append(support)
    persist(packet)
    with pytest.raises(CHECK.CorpusError):
        CHECK.validate_corpus(root)


def test_explicit_revision_filter_allows_reviewing_historical_source(packet):
    root, manifest, datasets = packet
    manifest["documents"][0]["active"] = False
    datasets[0]["questions"][0]["required_filters"] = [{"op": "eq", "field": "revision_id", "value": "r1"}]
    persist(packet)
    assert CHECK.validate_corpus(root)["questions"] == 1


def test_human_pending_blocks_review_gate_and_cannot_be_promoted_by_validator(packet):
    root, _, datasets = packet
    with pytest.raises(CHECK.CorpusError, match="human_review_pending"):
        CHECK.validate_corpus(root, require_human_review=True)
    assert datasets[0]["human_review"] == {"state": "pending", "reviewer": None}
    datasets[0]["human_review"] = {"state": "approved", "reviewer": "test-reviewer"}
    persist(packet)
    assert CHECK.validate_corpus(root, require_human_review=True)["human_review_pending"] == 0
    with pytest.raises(CHECK.CorpusError, match="human_review_pending"):
        CHECK.validate_corpus(root, include_held_out=True, require_human_review=True)


def test_cli_reports_safe_pending_review_code_without_private_input(packet, monkeypatch, capsys):
    root, _, datasets = packet
    datasets[0]["questions"][0]["query"] = "synthetic-private-query-secret"
    datasets[0]["questions"][0]["facets"][0]["question"] = "synthetic-private-facet-secret"
    persist(packet)
    monkeypatch.setattr("sys.argv", ["check_corpus.py", "--root", str(root), "--require-human-review"])
    assert CHECK.main() == 1
    output = capsys.readouterr()
    assert output.out == "Corpus validation failed: human_review_pending\n"
    assert not output.err
    assert "synthetic-private" not in output.out


def test_cli_keeps_unexpected_error_details_private(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise TypeError("synthetic-private-provider-secret")
    monkeypatch.setattr(CHECK, "validate_corpus", fail)
    monkeypatch.setattr("sys.argv", ["check_corpus.py"])
    assert CHECK.main() == 1
    assert capsys.readouterr().out == "Corpus validation failed.\n"
