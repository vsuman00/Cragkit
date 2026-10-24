import copy
import json
from pathlib import Path

import pytest

from cragkit._fusion import fuse
from cragkit.errors import IntegrityViolation, InvalidRequest

FIXTURE = json.loads((Path(__file__).resolve().parents[3] / 'contracts/fixtures/identifier_fusion.json').read_text())


@pytest.mark.parametrize('case', FIXTURE['cases'], ids=lambda case: case['id'])
def test_shared_arithmetic(case):
    before = copy.deepcopy(case['lists'])
    result = fuse(case['lists'], **case['options'])
    assert [item['candidate']['document_id'] for item in result] == [item[0] for item in case['expected']]
    assert [item['score'] for item in result] == pytest.approx([item[1] for item in case['expected']], abs=FIXTURE['tolerance'], rel=0)
    assert case['lists'] == before


@pytest.mark.parametrize('case', FIXTURE['invalid'], ids=lambda case: case['id'])
def test_shared_invalid(case):
    with pytest.raises({'invalid_request': InvalidRequest, 'integrity_violation': IntegrityViolation}[case['error']]):
        fuse(case['lists'], **case['options'])


def test_strict_limits_and_snapshot():
    for options in ({'k': True}, {'max_candidates': False}, {'k': -1}, {'max_candidates': 1001}):
        with pytest.raises(InvalidRequest):
            fuse([], **options)
    branches = copy.deepcopy(FIXTURE['cases'][0]['lists'])
    result = fuse(branches)
    original = copy.deepcopy(result)
    branches[0]['candidates'][0]['document_id'] = 'changed'
    assert result == original


def test_replay_provenance_and_complete_shapes():
    branch = copy.deepcopy(FIXTURE['cases'][0]['lists'][0])
    branch.update(list_id='z', facet_id='facet')
    replay = copy.deepcopy(branch)
    replay['list_id'] = 'a'
    result = fuse([branch, replay])
    assert all(len(item['contributions']) == 1 for item in result)
    assert all(item['contributions'][0]['list_id'] == 'a' for item in result)
    assert all(item['contributions'][0]['profile'] == 'fake_embedding_1536_v1' for item in result)
    del branch['candidates'][0]['embedding_profile']
    with pytest.raises(InvalidRequest):
        fuse([branch])


def test_bounded_lists_entries_and_union():
    branch = copy.deepcopy(FIXTURE['cases'][1]['lists'][0])
    branch['candidates'] = [branch['candidates'][0]] * 1000
    assert len(fuse([branch])) == 1
    branch['candidates'].append(branch['candidates'][0])
    with pytest.raises(InvalidRequest):
        fuse([branch])
    empty = [dict(branch, list_id=str(index), candidates=[]) for index in range(36)]
    assert fuse(empty) == []
    with pytest.raises(InvalidRequest):
        fuse([*empty, dict(branch, list_id='extra', candidates=[])])
    rows = [dict(FIXTURE['cases'][1]['lists'][0]['candidates'][0], document_id=str(index)) for index in range(1000)]
    branch['candidates'] = rows
    assert len(fuse([branch], max_candidates=1000)) == 1000
    with pytest.raises(InvalidRequest):
        fuse([branch], max_candidates=999)
