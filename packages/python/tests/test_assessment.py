import copy
import hashlib
import json
from pathlib import Path

import pytest

from cragkit.assessment import assess_evidence, validate_assessment
from cragkit.errors import InvalidRequest


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def evidence(text='four retries', name='e1', **changes):
    value = dict(evidence_id=name, collection='c', document_id='d', revision_id='r',
                 chunk_id=name, source_locator='fixture', start_byte=0, end_byte=len(text.encode()),
                 text=text, source_sha256=sha(text), text_sha256=sha(text))
    value.update(changes)
    return value


def anchor(item, claim='a'):
    return dict(claim_id=claim, **{key: item[key] for key in
                ('collection', 'document_id', 'revision_id', 'source_sha256',
                 'start_byte', 'end_byte', 'text')})


def facet(anchors, fid='f1', **changes):
    return dict(facet_id=fid, question='Which limit applies?', required=True,
                absence='missing', anchors=anchors, **changes)


def policy(facets, query='question'):
    return dict(policy_id='review', version='1', query_sha256=sha(query), facets=facets)


def test_default_unknown_and_query_boundary():
    for items, status in [([], 'insufficient'), ([evidence()], 'partial')]:
        result = assess_evidence('q' * 16384, items)
        assert result == dict(policy='unassessed.v0', status=status, facets=[dict(
            facet_id='query', question='Original query', required=True, state='unknown',
            evidence_ids=[], assessment_method='none', assessment_version='0')])
    for query in ['', ' \t\r\n', 'q' * 16385, '\ud800', 1, None]:
        with pytest.raises(InvalidRequest):
            assess_evidence(query, [])


def test_supported_compatible_alternatives_missing_unknown_and_required_facets():
    first, second = evidence(), evidence('five seconds', 'e2', document_id='delay')
    one = policy([facet([anchor(first), anchor(second)])])
    assert assess_evidence('question', [second, first], one)['facets'][0]['evidence_ids'] == ['e2', 'e1']
    assert assess_evidence('question', [first], one)['status'] == 'sufficient'
    for absence in ['missing', 'unknown']:
        f2 = facet([anchor(second)], 'f2')
        f2['absence'] = absence
        result = assess_evidence('question', [first], policy([facet([anchor(first)]), f2]))
        assert result['status'] == 'partial' and result['facets'][1]['state'] == absence
        assert result['facets'][1]['evidence_ids'] == []
    optional = facet([anchor(first)])
    optional['required'] = False
    assert assess_evidence('question', [first], policy([optional]))['status'] == 'partial'
    assert assess_evidence('question', [], one)['status'] == 'insufficient'


def test_declared_contradiction_cannot_be_hidden_by_projection_or_one_item():
    first, second = evidence(), evidence('three retries', 'e2', revision_id='old')
    configured = policy([facet([anchor(first), anchor(second, 'b')])])
    result = assess_evidence('question', [first, second], configured)
    assert result['facets'][0]['state'] == 'conflicting' and result['status'] == 'partial'
    for projection in [[first], [second]]:
        result = assess_evidence('question', projection, configured)
        assert result['facets'][0]['state'] == 'unknown' and result['status'] == 'partial'
    same_item = policy([facet([anchor(first), anchor(first, 'b')])])
    assert assess_evidence('question', [first], same_item)['facets'][0]['state'] == 'unknown'


@pytest.mark.parametrize('field,value', [('revision_id', 'other'), ('source_sha256', '0' * 64),
                                         ('document_id', 'other'), ('collection', 'other'),
                                         ('start_byte', 1), ('text', 'five retries')])
def test_matching_requires_identity_digest_offsets_and_exact_text(field, value):
    item = evidence()
    reviewed = anchor(item)
    reviewed[field] = value
    if field == 'start_byte':
        reviewed['end_byte'] += 1
    result = assess_evidence('question', [item], policy([facet([reviewed])]))
    assert result['facets'][0]['state'] == 'missing'


def test_containment_matches_but_disjoint_fragments_cannot_form_an_anchor():
    full = evidence('é alpha omega')
    reviewed = anchor(full)
    reviewed.update(start_byte=3, end_byte=8, text='alpha')
    assert assess_evidence('question', [full], policy([facet([reviewed])]))['status'] == 'sufficient'
    left = evidence('é alpha', start_byte=0, end_byte=8, source_sha256=full['source_sha256'])
    right = evidence('omega', 'e2', start_byte=9, end_byte=14, source_sha256=full['source_sha256'])
    result = assess_evidence('question', [left, right], policy([facet([anchor(full)])]))
    assert result['facets'][0]['state'] == 'missing'


def test_reassessment_after_only_facet_support_is_dropped():
    first, second = evidence(), evidence('five seconds', 'e2', document_id='delay')
    configured = policy([facet([anchor(first)]), facet([anchor(second)], 'f2')])
    assert assess_evidence('question', [first, second], configured)['status'] == 'sufficient'
    dropped = assess_evidence('question', [first], configured)
    assert dropped['status'] == 'partial' and dropped['facets'][1]['state'] == 'missing'
    assert assess_evidence('question', [], configured)['status'] == 'insufficient'


def test_copied_output_and_external_judge_validation():
    item = evidence()
    configured = policy([facet([anchor(item)])])
    result = assess_evidence('question', [item], configured)
    validated = validate_assessment([item], result['facets'])
    result['facets'][0]['evidence_ids'].clear()
    configured['facets'][0]['question'] = 'mutated'
    assert validated[0]['evidence_ids'] == ['e1'] and validated[0]['question'] == 'Which limit applies?'
    bad = copy.deepcopy(validated)
    for mutation in ['invented', 'duplicate', 'extra', 'conflicting', 'missing']:
        value = copy.deepcopy(bad)
        if mutation == 'invented': value[0]['evidence_ids'] = ['invented']
        elif mutation == 'duplicate': value.append(value[0])
        elif mutation == 'extra': value[0]['private'] = 'secret'
        else: value[0]['state'] = mutation
        with pytest.raises(InvalidRequest) as caught:
            validate_assessment([item], value)
        assert str(caught.value) == 'Invalid retrieval request.' and caught.value.__cause__ is None


@pytest.mark.parametrize('mutation', ['query', 'extra', 'facets', 'duplicate', 'required',
                                      'offset', 'anchor_extra', 'anchor_duplicate', 'version', 'scalar'])
def test_malformed_policy_rejected(mutation):
    item = evidence()
    configured = policy([facet([anchor(item)])])
    if mutation == 'query': configured['query_sha256'] = sha('different query')
    elif mutation == 'extra': configured['extra'] = True
    elif mutation == 'facets': configured['facets'] = []
    elif mutation == 'duplicate': configured['facets'] *= 2
    elif mutation == 'required': configured['facets'][0]['required'] = 1
    elif mutation == 'offset': configured['facets'][0]['anchors'][0]['start_byte'] = True
    elif mutation == 'anchor_extra': configured['facets'][0]['anchors'][0]['extra'] = 1
    elif mutation == 'anchor_duplicate': configured['facets'][0]['anchors'] *= 2
    elif mutation == 'version': configured['version'] = 'x' * 250
    else: configured['facets'][0]['anchors'][0]['text'] = '\ud800'
    with pytest.raises(InvalidRequest):
        assess_evidence('question', [item], configured)


def test_q19_reviewed_development_conflict_and_single_source_projections():
    path = Path(__file__).resolve().parents[3] / 'evaluation/questions/dev.json'
    question = next(q for q in json.loads(path.read_text())['questions'] if q['question_id'] == 'q19')
    supports = question['facets'][0]['support']
    items = [evidence(s['text'], f'e{index}', collection=question['collection'],
                      document_id=s['document_id'], revision_id=s['revision_id'],
                      source_sha256=s['canonical_sha256'], start_byte=s['start_byte'], end_byte=s['end_byte'])
             for index, s in enumerate(supports)]
    configured = policy([facet([anchor(item, str(index)) for index, item in enumerate(items)])], question['query'])
    for projection, state in [(items, 'conflicting'), (items[:1], 'unknown'), (items[1:], 'unknown')]:
        result = assess_evidence(question['query'], projection, configured)
        assert result['status'] == 'partial' and result['facets'][0]['state'] == state


def test_policy_limits_and_integral_wire_offsets():
    item = evidence()
    reviewed = anchor(item)
    reviewed['start_byte'] = 0.0
    reviewed['end_byte'] = float(reviewed['end_byte'])
    assert assess_evidence('question', [item], policy([facet([reviewed])]))['status'] == 'sufficient'
    for value in [0.5, -1, 9007199254740992, 10 ** 400]:
        invalid = anchor(item)
        invalid['start_byte'] = value
        with pytest.raises(InvalidRequest):
            assess_evidence('question', [item], policy([facet([invalid])]))
    for count in [17, 65]:
        anchors = [anchor(item, str(index)) for index in range(count)]
        facets = [facet(anchors)] if count == 17 else [facet(anchors[i:i + 16], str(i)) for i in range(0, count, 16)]
        with pytest.raises(InvalidRequest):
            assess_evidence('question', [item], policy(facets))
    large = evidence('a' * 32768)
    anchors = [anchor(large, str(index)) for index in range(9)]
    with pytest.raises(InvalidRequest):
        assess_evidence('question', [item], policy([facet(anchors)]))
