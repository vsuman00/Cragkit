"""Common native fixture and closed evidence protocol guards."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from check_backend_conformance import validate_result
from backend_conformance_fixture import conformance_input,cases,point


def test_common_fixture_has_valid_exact_baseline_and_distinct_partial_inventory():
    from cragkit._qdrant_writer_contract import prepare_stage
    value=conformance_input()
    assert prepare_stage(value['base']).member_count==1
    assert prepare_stage(value['foreign']).member_count==1
    assert prepare_stage(value['pending']).member_count==9
    base=value['base']['manifest'];pending=value['pending']['manifest']
    assert base['document_id']==pending['document_id'] and base['revision_id']!=pending['revision_id']
    assert value['pending']['intent']['expected_active_generation_id']==base['generation_id']
    assert value['foreign']['manifest']['tenant_id']!=base['tenant_id']
    partial=point(value['pending'],0,value['base']['intent']['initial_authorization'])
    assert partial['payload']['generation_id']==pending['generation_id']
    assert partial['vector']['dense'][1]==1 and len(pending['members'])==9
    assert [row['id'] for row in cases(value)]==['unknown','sufficient','partial','no_match','foreign_document','partial_generation','provider_budget']
    value['base']['manifest']['members'].clear()
    assert len(conformance_input()['base']['manifest']['members'])==1


@pytest.mark.parametrize('value',[{},dict(runtime='python',checks=[],route_calls=42,boundary_refusals=8,observations=[],cleanup_verified=True),
    dict(runtime='python',checks=[],route_calls=42,boundary_refusals=8,observations=[],cleanup_verified=True,credential='private')])
def test_incomplete_or_open_evidence_cannot_claim_matrix_completion(value):
    with pytest.raises(RuntimeError):validate_result(deepcopy(value),'python')


@pytest.mark.parametrize('entrypoint', ['check_typescript_backend_conformance.mjs', 'qdrant_publication_verification_cases.mjs'])
def test_node_entrypoint_resolves_checkout_dependencies_before_input(tmp_path, entrypoint):
    """Exercise the real ESM graph without starting services or passing queries."""
    import json
    import subprocess
    root=Path(__file__).resolve().parents[2]
    required=('packages/typescript/dist/qdrant-corrective.js',
              'packages/langchain-typescript/dist/index.js',
              'packages/mcp-typescript/dist/index.js',
              'packages/mcp-typescript/node_modules/@modelcontextprotocol/client')
    if not all((root/path).exists() for path in required):
        pytest.skip('Optional native SDK builds are required for this entrypoint smoke')
    directory=tmp_path/'unrelated working directory';directory.mkdir()
    result=subprocess.run(['node',str(root/'tools'/entrypoint)],
        input='',text=True,capture_output=True,cwd=directory,timeout=10,check=False)
    assert result.returncode==1 and result.stderr==''
    # Input rejection after module linking proves no root-level package is needed.
    value=json.loads(result.stdout)
    assert value['ok'] is False and isinstance(value['error'],str)
    if entrypoint=='check_typescript_backend_conformance.mjs':
        assert value['error']=='SyntaxError'
