"""Closed native purge evidence and fixture identity checks."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_qdrant_purge import validate_result
from qdrant_purge_cases import CHECKS, COMPLETED, purge_input, loads_managed_bodies


def test_purge_fixture_binds_distinct_documents_complete_graphs_and_exact_tombstones():
    from cragkit._qdrant_manifest import encode_security_intent, encode_purge_intent
    from cragkit._qdrant_writer_contract import prepare_stage
    value = purge_input()
    assert set(value['documents']) == {*COMPLETED, 'extra'}
    documents, points = set(), set()
    for item in value['documents'].values():
        first, second = item['stage'], item['second_stage']
        for stage in (first, second):
            prepare_stage(stage)
            ids = {member['point_id'] for member in stage['manifest']['members']}
            assert len(ids) == 2 and not points.intersection(ids)
            points.update(ids)
        document = first['manifest']['document_id']
        assert document not in documents
        documents.add(document)
        assert second['intent']['expected_active_generation_id'] == first['manifest']['generation_id']
        assert item['purge']['tombstone_intent_payload_sha256'] == encode_security_intent(item['tombstone']).sha256
        encode_purge_intent(item['purge'])
        assert item['tombstone']['authorization']['tombstoned'] is True
    changed = deepcopy(value)
    changed['documents']['base']['stage']['dense_vectors'][0][0] = 99
    assert purge_input()['documents']['base']['stage']['dense_vectors'][0][0] != 99


def test_purge_native_evidence_cannot_substitute_partial_or_physical_only_results():
    assert len(CHECKS) == len(set(CHECKS)) == 8
    for runtime in ('python', 'typescript'):
        value = dict(runtime=runtime, checks=list(CHECKS), proof_scope='native_managed_purge_only',
            semantic_witness_sha256='a'*64)
        assert validate_result(value, runtime) == value
        for changed in (dict(value, checks=[]), dict(value, proof_scope='physical_absence'),
                dict(value, semantic_witness_sha256=True), dict(value, private='source')):
            with pytest.raises(RuntimeError):
                validate_result(changed, runtime)


@pytest.mark.parametrize('sql,expected', [
    ('SELECT canonical_utf8,source_sha256 FROM cragkit_qdrant.document_revisions WHERE tenant_id=%s', True),
    ('SELECT dense_blob,sparse_blob FROM cragkit_qdrant.vector_replays WHERE tenant_id=%s', True),
    ('SELECT content_erased,canonical_utf8 IS NULL FROM cragkit_qdrant.document_revisions WHERE tenant_id=%s', False),
    ('SELECT request_bytes IS NOT NULL,request_original_bytes FROM cragkit_qdrant.dispatch_journal WHERE tenant_id=%s', False),
    ("SELECT has_column_privilege('canonical_utf8') FROM pg_catalog.pg_roles", False),
])
def test_native_body_spy_distinguishes_body_loading_from_retained_markers_and_catalog(sql, expected):
    assert loads_managed_bodies(sql) is expected
