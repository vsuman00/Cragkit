"""Check local corpus labels and source spans without running retrieval."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


class CorpusError(ValueError):
    """A corpus invariant failed; messages contain no source or question text."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise CorpusError(code)


def object_keys(value: Any, required: set[str], code: str) -> dict[str, Any]:
    require(type(value) is dict and set(value) == required, code)
    return value


def identity(value: Any) -> bool:
    if type(value) is not str or not value.strip(" \t\r\n\f\v"):
        return False
    try:
        return len(value.encode("utf-8")) <= 256
    except UnicodeError:
        return False


def text(value: Any) -> bool:
    if type(value) is not str or not value.strip(" \t\r\n\f\v"):
        return False
    try:
        value.encode("utf-8")
        return True
    except UnicodeError:
        return False


def load_json(path: Path) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(CorpusError("nonfinite_json")))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise CorpusError("unreadable_json") from None


def validate_corpus(root: Path, include_held_out: bool = False,
                    require_human_review: bool = False) -> dict[str, int]:
    corpus = (root / "evaluation/corpus").resolve()
    manifest = object_keys(load_json(corpus / "manifest.json"), {"schema_version", "documents"}, "manifest_shape")
    require(manifest["schema_version"] == "0.1", "manifest_version")
    require(type(manifest["documents"]) is list and bool(manifest["documents"]), "documents_shape")
    documents: dict[tuple[str, str, str, str], tuple[dict[str, Any], bytes]] = {}
    families: dict[str, str] = {}
    active: set[tuple[str, str, str]] = set()
    paths: set[Path] = set()
    counts = {"documents": 0, "development_documents": 0, "held_out_documents": 0,
              "questions": 0, "facets": 0, "support_spans": 0, "datasets": 0, "human_review_pending": 0}
    for raw in manifest["documents"]:
        item = object_keys(raw, {"tenant_id", "collection", "document_id", "revision_id", "family_id",
                                 "split", "active", "path", "canonical_sha256"}, "document_shape")
        require(all(identity(item[key]) for key in ("tenant_id", "collection", "document_id", "revision_id", "family_id")), "document_identity")
        require(item["split"] in ("development", "held_out") and type(item["active"]) is bool, "document_metadata")
        family = item["family_id"]
        require(family not in families or families[family] == item["split"], "family_split_leak")
        families[family] = item["split"]
        key = tuple(item[field] for field in ("tenant_id", "collection", "document_id", "revision_id"))
        require(key not in documents, "duplicate_document_revision")
        require(type(item["path"]) is str and not Path(item["path"]).is_absolute(), "source_path")
        path = (corpus / item["path"]).resolve()
        require(path.is_relative_to(corpus) and path != corpus and path not in paths, "source_path")
        paths.add(path)
        try:
            content = path.read_bytes()
            content.decode("utf-8", errors="strict")
        except (OSError, UnicodeError):
            raise CorpusError("unreadable_source") from None
        require(hashlib.sha256(content).hexdigest() == item["canonical_sha256"], "source_digest")
        documents[key] = (item, content)
        if item["active"]:
            require(key[:3] not in active, "multiple_active_revisions")
            active.add(key[:3])
        counts["documents"] += 1
        counts[f'{item["split"]}_documents'] += 1
    question_ids: set[str] = set()
    facet_ids: set[str] = set()
    splits = [("development", "dev.json")]
    if include_held_out:
        splits.append(("held_out", "held_out.json"))
    for split, filename in splits:
        dataset = object_keys(load_json(root / "evaluation/questions" / filename),
                              {"schema_version", "origin", "human_review", "questions"}, "dataset_shape")
        require(dataset["schema_version"] == "0.1" and dataset["origin"] == "synthetic", "dataset_metadata")
        review = object_keys(dataset["human_review"], {"state", "reviewer"}, "review_shape")
        require((review["state"] == "pending" and review["reviewer"] is None)
                or (review["state"] == "approved" and identity(review["reviewer"])), "review_state")
        if review["state"] == "pending":
            counts["human_review_pending"] += 1
        require(not require_human_review or review["state"] == "approved", "human_review_pending")
        require(type(dataset["questions"]) is list, "questions_shape")
        counts["datasets"] += 1
        for raw in dataset["questions"]:
            question = object_keys(raw, {"question_id", "tenant_id", "collection", "query", "required_filters", "answerability", "facets"}, "question_shape")
            require(all(identity(question[key]) for key in ("question_id", "tenant_id", "collection")) and text(question["query"]), "question_identity")
            require(question["question_id"] not in question_ids, "duplicate_question_id")
            question_ids.add(question["question_id"])
            require(question["answerability"] in ("answerable", "partially_answerable", "unanswerable"), "answerability")
            require(type(question["required_filters"]) is list, "filters_shape")
            filters: dict[str, Any] = {}
            for raw_filter in question["required_filters"]:
                filt = object_keys(raw_filter, {"op", "field", "value"}, "filter_shape")
                require(filt["op"] == "eq" and filt["field"] in ("document_id", "revision_id") and identity(filt["value"]), "filter_value")
                require(filt["field"] not in filters, "duplicate_filter")
                filters[filt["field"]] = filt["value"]
            require(type(question["facets"]) is list and bool(question["facets"]), "facets_shape")
            states: list[str] = []
            for raw_facet in question["facets"]:
                facet = object_keys(raw_facet, {"facet_id", "question", "state", "support"}, "facet_shape")
                require(identity(facet["facet_id"]) and text(facet["question"]), "facet_identity")
                require(facet["facet_id"] not in facet_ids, "duplicate_facet_id")
                facet_ids.add(facet["facet_id"])
                require(facet["state"] in ("supported", "missing", "conflicting") and type(facet["support"]) is list, "facet_state")
                spans: set[tuple[Any, ...]] = set()
                for raw_support in facet["support"]:
                    support = object_keys(raw_support, {"document_id", "revision_id", "start_byte", "end_byte", "text", "canonical_sha256"}, "support_shape")
                    require(identity(support["document_id"]) and identity(support["revision_id"]), "support_identity")
                    key = (question["tenant_id"], question["collection"], support["document_id"], support["revision_id"])
                    require(key in documents, "support_scope_or_revision")
                    item, content = documents[key]
                    require(item["split"] == split, "support_split")
                    require(all(item[field] == value for field, value in filters.items()), "support_filter")
                    require("revision_id" in filters or item["active"], "inactive_support")
                    start, end = support["start_byte"], support["end_byte"]
                    require(type(start) is int and type(end) is int and 0 <= start < end <= len(content), "support_span")
                    require(type(support["text"]) is str, "support_text")
                    try:
                        excerpt = content[start:end].decode("utf-8", errors="strict")
                        encoded = support["text"].encode("utf-8", errors="strict")
                    except UnicodeError:
                        raise CorpusError("support_unicode_boundary") from None
                    require(excerpt == support["text"] and content[start:end] == encoded, "support_excerpt")
                    require(support["canonical_sha256"] == item["canonical_sha256"], "support_digest")
                    ref = (support["document_id"], support["revision_id"], start, end)
                    require(ref not in spans, "duplicate_support")
                    spans.add(ref)
                    counts["support_spans"] += 1
                size = len(spans)
                require((facet["state"] == "missing" and size == 0)
                        or (facet["state"] == "supported" and size >= 1)
                        or (facet["state"] == "conflicting" and size >= 2), "facet_support")
                states.append(facet["state"])
                counts["facets"] += 1
            label = question["answerability"]
            require((label == "answerable" and all(state == "supported" for state in states))
                    or (label == "partially_answerable" and any(state != "missing" for state in states)
                        and any(state != "supported" for state in states))
                    or (label == "unanswerable" and all(state == "missing" for state in states)), "answerability_facets")
            counts["questions"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--include-held-out", action="store_true")
    parser.add_argument("--require-human-review", action="store_true")
    args = parser.parse_args()
    try:
        counts = validate_corpus(args.root, args.include_held_out, args.require_human_review)
    except CorpusError as error:
        print(f"Corpus validation failed: {error}")
        return 1
    except (TypeError, KeyError, ValueError):
        print("Corpus validation failed.")
        return 1
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
