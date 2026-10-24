"""Pure ranking metrics for reviewed labels and already verified evidence.

Ranks count distinct document/revision identities. Span coverage uses the union
of returned spans belonging to the first k identities. These metrics do not
assess source truth, answer correctness, or semantic confidence.
"""
from math import log2
from statistics import fmean


def _identity(span):
    return span['document_id'], span['revision_id']


def _covered(reference, spans):
    """Require continuous coverage of a half-open reference byte interval."""
    cursor = reference['start_byte']
    for start, end in sorted(spans.get(_identity(reference), [])):
        if start > cursor:
            break
        cursor = max(cursor, end)
        if cursor >= reference['end_byte']:
            return True
    return False


def score_question(question, evidence, k=5):
    """Score one validated label; evidence must be a normalized list of dicts.

    Supported facets accept any listed support; conflicting facets require all
    listed supports. Facets without support have no support-recall denominator.
    Unanswerable evidence is a separate diagnostic, never a confidence estimate.
    """
    if type(k) is not int or k < 1:
        raise ValueError('invalid_k')
    if not isinstance(evidence, list):
        raise ValueError('malformed_evidence')
    for item in evidence:
        if not isinstance(item, dict) or any(
            not isinstance(item.get(key), str) or not item[key]
            for key in ('document_id', 'revision_id')
        ):
            raise ValueError('malformed_evidence')
        start, end = item.get('start_byte'), item.get('end_byte')
        if type(start) is not int or type(end) is not int or start < 0 or end <= start:
            raise ValueError('malformed_evidence')

    ranked = list(dict.fromkeys(_identity(item) for item in evidence))[:k]
    selected = set(ranked)
    spans = {}
    for item in evidence:
        key = _identity(item)
        if key in selected:
            spans.setdefault(key, []).append((item['start_byte'], item['end_byte']))
    facets = [facet for facet in question['facets']
              if facet['state'] in ('supported', 'conflicting') and facet['support']]
    positives = {_identity(ref) for facet in facets for ref in facet['support']}
    hits = [rank for rank, key in enumerate(ranked, 1) if key in positives]
    count = len(positives)
    ideal = sum(1 / log2(rank + 1) for rank in range(1, min(k, count) + 1))
    covered = sum(
        (all if facet['state'] == 'conflicting' else any)(
            _covered(ref, spans) for ref in facet['support']
        )
        for facet in facets
    )
    return {
        'question_id': question['question_id'],
        'positive_document_count': count,
        'document_recall_at_k': len(hits) / count if count else None,
        'reciprocal_rank': (1 / hits[0] if hits else 0.0) if count else None,
        'ndcg_at_k': sum(1 / log2(rank + 1) for rank in hits) / ideal if count else None,
        'facet_support_recall_at_k': covered / len(facets) if facets else None,
        'evidence_on_unanswerable': bool(evidence) if question['answerability'] == 'unanswerable' else None,
    }


def aggregate(rows):
    """Return macro averages, excluding undefined question metrics."""
    rows = list(rows)
    result = {
        'total_questions': len(rows),
        'positive_questions': sum(row['positive_document_count'] > 0 for row in rows),
        'unanswerable_questions': sum(row['evidence_on_unanswerable'] is not None for row in rows),
    }
    for field in ('document_recall_at_k', 'reciprocal_rank', 'ndcg_at_k',
                  'facet_support_recall_at_k'):
        values = [row[field] for row in rows if row[field] is not None]
        result[field] = fmean(values) if values else None
    flags = [row['evidence_on_unanswerable'] for row in rows
             if row['evidence_on_unanswerable'] is not None]
    result['evidence_on_unanswerable_rate'] = fmean(flags) if flags else None
    return result
