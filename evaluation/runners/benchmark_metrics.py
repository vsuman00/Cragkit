"""Independent reviewed-label metrics; no runtime assessor or filesystem access."""
from hashlib import sha256
from math import log2, sqrt
from statistics import fmean

METRIC_VERSION = 'V6-reviewed-span-r1'
IDENTITY = ('tenant_id', 'collection', 'document_id', 'revision_id')
RANKING = ('document_recall_at_k', 'reciprocal_rank', 'ndcg_at_k', 'facet_support_recall_at_k')
FLAGS = ('false_sufficient', 'abstention', 'answerable_abstention', 'conflict_miss',
         'abstention_correct', 'required_abstention', 'degraded', 'operational_failure',
         'identity_violation', 'authorization_violation', 'fidelity_violation')


def _key(item):
    return tuple(item[field] for field in IDENTITY)


def _covered(reference, spans):
    cursor = reference['start_byte']
    for start, end in sorted(spans.get((reference['document_id'], reference['revision_id']), [])):
        if start > cursor:
            break
        cursor = max(cursor, end)
        if cursor >= reference['end_byte']:
            return True
    return False


def score_question(question, result, *, manifest, sources, k=5):
    """Score a reviewed question against a parsed native result or explicit failure.

    Sources map full (tenant, collection, document, revision) tuples to canonical
    UTF-8 bytes or strings. A failure is {'operational_failure': True}; it is not
    fabricated into an insufficient result. Labels/snapshots must be prevalidated.
    """
    if type(k) is not int or k < 1:
        raise ValueError('invalid_k')
    records = {_key(doc): doc for doc in manifest['documents']}
    if len(records) != len(manifest['documents']):
        raise ValueError('duplicate_manifest_identity')
    failure = result.get('operational_failure') is True
    if failure and any(field in result for field in ('status', 'evidence', 'facets')):
        raise ValueError('failure_is_not_result')
    if not failure and (result.get('status') not in ('sufficient', 'partial', 'insufficient')
                        or result.get('execution', 'complete') not in ('complete', 'degraded')):
        raise ValueError('invalid_result')
    filters = {}
    for filt in question['required_filters']:
        if filt['op'] != 'eq' or filt['field'] not in ('document_id', 'revision_id') or filt['field'] in filters:
            raise ValueError('unsupported_label_filter')
        filters[filt['field']] = filt['value']
    violations = dict(identity=0, authorization=0, fidelity=0)
    valid = []
    for item in result.get('evidence', []):
        key = (item.get('tenant_id', question['tenant_id']), item.get('collection'),
               item.get('document_id'), item.get('revision_id'))
        doc = records.get(key)
        if doc is None:
            violations['identity'] += 1
        authorized = (key[:2] == (question['tenant_id'], question['collection'])
                      and all(item.get(field) == value for field, value in filters.items())
                      and (doc is None or doc['active'] or 'revision_id' in filters))
        if not authorized:
            violations['authorization'] += 1
        if doc is None or not authorized:
            continue
        raw = sources.get(key)
        if raw is None:
            raise ValueError('missing_source_snapshot')
        raw = raw.encode('utf-8') if isinstance(raw, str) else raw
        if type(raw) is not bytes or sha256(raw).hexdigest() != doc['canonical_sha256']:
            raise ValueError('invalid_source_snapshot')
        try:
            start, end = item['start_byte'], item['end_byte']
            excerpt = item['text'].encode('utf-8')
            okay = (type(start) is int and type(end) is int and 0 <= start < end <= len(raw)
                    and raw[start:end].decode('utf-8').encode('utf-8') == excerpt
                    and item['source_sha256'] == doc['canonical_sha256']
                    and item['text_sha256'] == sha256(excerpt).hexdigest())
        except (KeyError, AttributeError, UnicodeError):
            okay = False
        if not okay:
            violations['fidelity'] += 1
        else:
            valid.append(item)
    ranked = list(dict.fromkeys((i.get('document_id'), i.get('revision_id'))
                               for i in result.get('evidence', [])))[:k]
    valid_keys = {(i['document_id'], i['revision_id']) for i in valid}
    def spans_for(items):
        spans = {}
        for item in items:
            spans.setdefault((item['document_id'], item['revision_id']), []).append((item['start_byte'], item['end_byte']))
        return spans
    selected = set(ranked)
    spans = spans_for(i for i in valid if (i['document_id'], i['revision_id']) in selected)
    all_spans = spans_for(valid)
    facets = [f for f in question['facets'] if f['state'] in ('supported', 'conflicting') and f['support']]
    positives = {(ref['document_id'], ref['revision_id']) for f in facets for ref in f['support']}
    hits = [rank for rank, key in enumerate(ranked, 1) if key in positives and key in valid_keys]
    def facet_covered(facet, intervals):
        return (all if facet['state'] == 'conflicting' else any)(_covered(ref, intervals) for ref in facet['support'])
    sufficient_truth = (question['answerability'] == 'answerable' and bool(question['facets'])
                        and all(f['state'] == 'supported' and f['support'] and facet_covered(f, all_spans)
                                for f in question['facets']) and not any(violations.values()))
    sufficient = not failure and result['status'] == 'sufficient'
    abstains = not sufficient
    conflict_facets = [f for f in question['facets'] if f['state'] == 'conflicting']
    actual_states = {f['facet_id']: f['state'] for f in result.get('facets', [])}
    required_abstention = question['answerability'] != 'answerable'
    ideal = sum(1/log2(rank+1) for rank in range(1, min(k, len(positives))+1))
    return dict(metric_version=METRIC_VERSION, question_id=question['question_id'], k=k,
        positive_document_count=len(positives), support_facet_count=len(facets),
        document_recall_at_k=len(hits)/len(positives) if positives else None,
        reciprocal_rank=(1/hits[0] if hits else 0.0) if positives else None,
        ndcg_at_k=sum(1/log2(rank+1) for rank in hits)/ideal if ideal else None,
        facet_support_recall_at_k=sum(facet_covered(f, spans) for f in facets)/len(facets) if facets else None,
        false_sufficient=(sufficient and not sufficient_truth) if not failure else None,
        abstention=abstains if not failure else None,
        answerable_abstention=abstains if not failure and question['answerability'] == 'answerable' else None,
        conflict_miss=any(actual_states.get(f['facet_id']) != 'conflicting' for f in conflict_facets) if conflict_facets and not failure else None,
        abstention_correct=required_abstention if abstains and not failure else None,
        required_abstention=abstains if required_abstention and not failure else None,
        degraded=(result.get('execution', 'complete') == 'degraded') if not failure else None,
        operational_failure=failure, usage=result.get('usage'),
        **{name+'_violation': count > 0 for name, count in violations.items()},
        violation_counts=violations)


def _rate(values):
    n, count = len(values), sum(values)
    if not n:
        return dict(count=0, denominator=0, rate=None, wilson95=None)
    p, z = count/n, 1.959963984540054
    center = (p+z*z/(2*n))/(1+z*z/n)
    half = z*sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    return dict(count=count, denominator=n, rate=p, wilson95=[max(0., center-half), min(1., center+half)])


def aggregate(rows):
    """Macro means and descriptive Wilson intervals; never impute unknown usage."""
    rows = list(rows)
    if any(row['metric_version'] != METRIC_VERSION for row in rows) or len({row['k'] for row in rows}) > 1:
        raise ValueError('mixed_metric_configuration')
    if len({row['question_id'] for row in rows}) != len(rows):
        raise ValueError('duplicate_question')
    output = dict(metric_version=METRIC_VERSION, total_questions=len(rows), k=rows[0]['k'] if rows else None)
    for field in RANKING:
        values = [row[field] for row in rows if row[field] is not None]
        output[field] = dict(mean=fmean(values) if values else None, denominator=len(values))
    for field in FLAGS:
        output[field] = _rate([row[field] for row in rows if row[field] is not None])
    output['violation_counts'] = {name: sum(row['violation_counts'][name] for row in rows)
                                  for name in ('identity', 'authorization', 'fidelity')}
    output['usage_records'] = [row['usage'] for row in rows]
    output['usage_missing_questions'] = sum(row['usage'] is None for row in rows)
    return output
