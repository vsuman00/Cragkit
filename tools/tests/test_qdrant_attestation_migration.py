"""Static G0 migration contracts; real SQL constraints are exercised separately."""
from hashlib import sha256
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / 'storage/qdrant/postgres/migrations'
SQL = (DIRECTORY / '0003_preparation_attestations.sql').read_text()
OLD = (DIRECTORY / '0002_publication.sql').read_text()
COLUMNS = (
    'tenant_id', 'collection', 'document_id', 'intent_id', 'instance_id', 'owner_token',
    'backend_epoch', 'authorization_revision', 'mutation_epoch', 'manifest_sha256',
    'expected_active_generation_id', 'credential_generation', 'verification_id', 'readback_sha256',
)


def function(source, name):
    marker = 'FUNCTION cragkit_qdrant.' + name + '('
    start = source.index(marker)
    body = source.index('AS $function$', start) + len('AS $function$')
    end = source.index('$function$;', body)
    return source[body:end]


def test_applied_migrations_remain_byte_identical_and_upgrade_requires_exact_history():
    for version, expected in (
        ('0001_authority', '3d75cd46eb32a10864f1097a7494b01f9759150911a7cd9a1e6aab60105c1f1a'),
        ('0002_publication', '386fe01d0d03e35ac35c21bce598b21bff2c5ad510e9cdf0a6fbe56f359b6661'),
    ):
        assert sha256((DIRECTORY / (version + '.sql')).read_bytes()).hexdigest() == expected
        assert "version = '" + version + "'" in SQL and expected in SQL
    assert '(SELECT count(*) FROM cragkit_qdrant.schema_migrations) <> 2' in SQL
    assert not re.search(r'(?mi)^\s*(?:BEGIN\s*;|COMMIT|ROLLBACK|\\)', SQL)
    assert not re.search(r'(?i)ALTER\s+TABLE\s+cragkit_qdrant\.(?:preparations|publication_intents|generations|document_revisions)\b', SQL)


def test_exact_attestation_columns_and_original_scoped_preparation_foreign_key():
    table = SQL.split('CREATE TABLE cragkit_qdrant.preparation_attestations (', 1)[1].split('\n);', 1)[0]
    columns = re.findall(r'^    ([a-z_][a-z0-9_]*) (?!KEY\b)(?:cragkit_qdrant\.|uuid\b)', table, re.M)
    assert tuple(columns) == COLUMNS
    assert 'PRIMARY KEY (tenant_id, collection, document_id, intent_id, backend_epoch, owner_token)' in table
    assert ('FOREIGN KEY (tenant_id, collection, document_id, intent_id)\n'
            '        REFERENCES cragkit_qdrant.preparations (tenant_id, collection, document_id, intent_id)') in table
    assert 'expected_active_generation_id cragkit_qdrant.identity_text,' in table
    assert 'instance_id cragkit_qdrant.identity_text NOT NULL REFERENCES cragkit_qdrant.backend_instances' in table


def test_invoker_guards_writer_only_append_privileges_and_exact_scope_policies():
    assert 'ENABLE ROW LEVEL SECURITY' in SQL and 'FORCE ROW LEVEL SECURITY' in SQL
    assert not re.search(r'(?i)SECURITY\s+DEFINER', SQL)
    assert 'LANGUAGE plpgsql SET search_path = pg_catalog' in SQL
    grants = re.findall(r'GRANT\s+([^;]+);', SQL)
    assert len(grants) == 2
    assert 'SELECT, INSERT ON cragkit_qdrant.preparation_attestations TO cragkit_qdrant_writer' in grants
    assert 'EXECUTE ON FUNCTION cragkit_qdrant.assert_publication(text,text,text,text) TO cragkit_qdrant_writer' in grants
    assert 'FROM PUBLIC, cragkit_qdrant_writer, cragkit_qdrant_supervisor' in SQL
    for policy in ('writer_attestation_read', 'writer_attestation_insert'):
        body = SQL.split('CREATE POLICY ' + policy, 1)[1].split(';', 1)[0]
        assert 'cragkit_qdrant.writer_scope(tenant_id,collection,document_id)' in body
        assert "intent_id = current_setting('cragkit_qdrant.writer_intent_id',true)" in body
        assert "instance_id = current_setting('cragkit_qdrant.backend_instance_id',true)" in body
        assert 'owner_token =' not in body  # Historical tuples remain visible to same-intent reconciliation.
    guard = function(SQL, 'guard_preparation_attestation')
    assert "IF TG_OP <> 'INSERT' THEN" in guard
    assert 'BEFORE INSERT OR UPDATE OR DELETE ON cragkit_qdrant.preparation_attestations' in SQL
    assert not re.search(r'(?i)GRANT\s+[^;]*(?:UPDATE|DELETE|TRUNCATE)', SQL)


def test_attestation_lock_order_and_fresh_fences_preserve_prepared_and_old_preparation():
    guard = function(SQL, 'guard_preparation_attestation')
    backend_owner = guard.index('PERFORM cragkit_qdrant.lock_publication_owner(')
    document_lock = guard.index('FOR UPDATE;')
    owner_read = guard.index('SELECT instance_id,owner_token,backend_epoch,intent_id INTO owner_row')
    assert backend_owner < document_lock < owner_read
    for condition in (
        "intent_row.action <> 'stage' OR intent_row.state <> 'prepared'",
        'NEW.backend_epoch <= original.backend_epoch',
        'NEW.expected_active_generation_id,NEW.authorization_revision,NEW.mutation_epoch',
        "current_setting('cragkit_qdrant.writer_owner_token',true)",
        "current_setting('cragkit_qdrant.writer_intent_id',true)",
        "current_setting('cragkit_qdrant.backend_instance_id',true)",
        'document_row.tombstoned', "AND state <> 'settled'",
        'original.instance_id,original.manifest_sha256,original.authorization_revision,original.mutation_epoch',
    ):
        assert condition in guard
    assert not re.search(r'(?i)\b(?:UPDATE|DELETE|INSERT INTO)\s+cragkit_qdrant\.(?:preparations|publication_intents)', guard)
    for relation in ('members', 'point_claims', 'vector_replays'):
        assert '(SELECT count(*) FROM cragkit_qdrant.' + relation in guard
    assert 'claim.point_id IS NULL OR replay.point_id IS NULL' in guard


def test_final_assertion_keeps_every_original_outcome_and_graph_guard():
    original = function(OLD, 'assert_publication')
    replacement = function(SQL, 'assert_publication')
    # This suffix includes all original outcome/security/pointer/journal and complete-graph checks.
    marker = "    IF NOT FOUND OR intent_row.action <> 'stage'"
    assert replacement[replacement.index(marker):] == original[original.index(marker):]
    assert 'CREATE OR REPLACE FUNCTION cragkit_qdrant.assert_publication(' in SQL
    assert 'FOR UPDATE;' in replacement
    assert 'attestation.backend_epoch = owner_row.backend_epoch AND attestation.owner_token = owner_row.owner_token' in replacement
    assert 'attestation.expected_active_generation_id IS NOT DISTINCT FROM intent_row.expected_active_generation_id' in replacement
    assert 'attestation.backend_epoch > original.backend_epoch' in replacement
    assert 'FROM cragkit_qdrant.preparations AS original' in replacement
    assert not re.search(r'(?i)\b(?:max\s*\(|ORDER\s+BY|LIMIT\s+1)', replacement)
