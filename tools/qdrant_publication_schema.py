"""Bounded, explicit SQL acceptance probes for the additive publication schema.

The caller owns the admin connection and rollback-only transaction. This module
does not connect, provision a service, commit, or perform Qdrant operations.
"""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json
import re
import secrets
import struct
from copy import deepcopy

from qdrant_authority_schema import ROOT, literal

CAPABILITY_ROLES = ('cragkit_qdrant_writer', 'cragkit_qdrant_supervisor')
MIGRATION = ROOT / 'storage/qdrant/postgres/migrations/0002_publication.sql'
DELIMITER = '$qw_probe$'


@dataclass(frozen=True)
class PublicationMigration:
    version: str
    checksum: str
    sql: str


def migration(path: Path = MIGRATION) -> PublicationMigration:
    """Bind exact administrative migration bytes without applying them."""
    if path.name != '0002_publication.sql':
        raise ValueError('publication_migration_identity')
    raw = path.read_bytes()
    sql = raw.decode('utf-8')
    if '\r' in sql or re.search(r'(?mi)^\s*(?:COMMIT|ROLLBACK|BEGIN\s*;|\\)', sql):
        raise ValueError('publication_transaction_boundary')
    if DELIMITER in sql:
        raise ValueError('publication_probe_delimiter')
    return PublicationMigration(path.stem, sha256(raw).hexdigest(), sql)


def assert_sql(condition: str, label: str) -> str:
    """Construct a fixed-label assertion over trusted synthetic probe SQL."""
    if type(condition) is not str or DELIMITER in condition:
        raise ValueError('publication_probe_condition')
    if type(label) is not str or re.fullmatch(r'[a-z0-9_]{1,80}', label) is None:
        raise ValueError('publication_probe_label')
    return (f'DO {DELIMITER} BEGIN IF ({condition}) IS DISTINCT FROM true THEN '
            f"RAISE EXCEPTION '{label}'; END IF; END {DELIMITER};")


def rejected_sql(statement: str, sqlstate: str) -> str:
    """Expect one precise SQLSTATE without swallowing unrelated failures."""
    if type(statement) is not str or DELIMITER in statement:
        raise ValueError('publication_probe_statement')
    if type(sqlstate) is not str or re.fullmatch(r'[0-9A-Z]{5}', sqlstate) is None:
        raise ValueError('publication_probe_sqlstate')
    return (f'DO {DELIMITER} DECLARE observed boolean := false; BEGIN BEGIN {statement} '
            f"EXCEPTION WHEN SQLSTATE '{sqlstate}' THEN observed := true; END; "
            "IF NOT observed THEN RAISE EXCEPTION 'publication_invalid_write_accepted'; "
            f'END IF; END {DELIMITER};')


def rolled_back_case_sql(statements: list[str]) -> str:
    """Run a successful transition, assert it, then roll back its subtransaction."""
    if type(statements) is not list or not statements or any(type(item) is not str or DELIMITER in item for item in statements):
        raise ValueError('publication_probe_case')
    return (f'DO {DELIMITER} BEGIN BEGIN ' + '\n'.join(statements)
            + " RAISE SQLSTATE 'QW001'; EXCEPTION WHEN SQLSTATE 'QW001' THEN NULL; END; "
            + f'END {DELIMITER};')


def rejected_block(statement: str, sqlstate: str = '23514') -> str:
    """Embed an exact-state negative inside a rolled-back positive case."""
    # Reuse the checked constructor, removing only its fixed outer DO wrapper.
    checked = rejected_sql(statement, sqlstate)
    return checked.removeprefix(f'DO {DELIMITER} ').removesuffix(f' {DELIMITER};') + ';'


def publication_fixture(path: Path = ROOT / 'contracts/fixtures/qdrant_publication.json') -> dict:
    """Resolve only committed synthetic material, not caller credentials/source."""
    fixture = json.loads(path.read_text(encoding='utf-8'))
    source = fixture['source_revision']['canonical_utf8']['value'].encode('utf-8')
    if sha256(source).hexdigest() != fixture['source_revision']['source_sha256']:
        raise ValueError('publication_fixture_source_digest')
    for member in fixture['members']:
        excerpt = source[member['start_byte']:member['end_byte']]
        if sha256(excerpt).hexdigest() != member['text_sha256']:
            raise ValueError('publication_fixture_excerpt_digest')
    return fixture


def insert_sql(table: str, record: dict) -> str:
    """Quote synthetic values while allowing only fixed identifier spellings."""
    if type(table) is not str or re.fullmatch(r'[a-z_][a-z0-9_]{0,62}', table) is None:
        raise ValueError('publication_fixture_table')
    if type(record) is not dict or not record:
        raise ValueError('publication_fixture_record')
    for column in record:
        if type(column) is not str or re.fullmatch(r'[a-z_][a-z0-9_]{0,62}', column) is None:
            raise ValueError('publication_fixture_column')
    values = []
    for value in record.values():
        if type(value) is dict:
            values.append(literal(json.dumps(value, ensure_ascii=False, separators=(',', ':'))) + '::jsonb')
        elif type(value) is list:
            values.append('ARRAY[' + ','.join(literal(item) for item in value) + ']::text[]')
        else:
            values.append(literal(value))
    return f"INSERT INTO cragkit_qdrant.{table} ({','.join(record)}) VALUES ({','.join(values)});"


def replay_blob(kind: str, values: list, indices: list | None = None) -> bytes:
    """Construct only the bounded original-vector sidecar used by this fixture."""
    if kind not in ('dense', 'sparse') or type(values) is not list:
        raise ValueError('publication_fixture_replay')
    if kind == 'dense' and (len(values) != 1536 or indices is not None):
        raise ValueError('publication_fixture_replay')
    if kind == 'sparse' and (type(indices) is not list or not 1 <= len(values) <= 16
                             or len(indices) != len(values)):
        raise ValueError('publication_fixture_replay')
    name = kind.encode('ascii')
    result = b'cragkit.qdrant.replay.v1\0' + struct.pack('<I', len(name)) + name + struct.pack('<I', len(values))
    if indices is not None:
        result += b''.join(struct.pack('<I', index) for index in indices)
    return result + b''.join(struct.pack('<d', value) for value in values)


def seed_records(fixture: dict | None = None) -> dict:
    """Build one complete two-member staged generation from frozen goldens."""
    fixture = publication_fixture() if fixture is None else fixture
    document = fixture['document']
    source = fixture['source_revision']
    common = {key: document[key] for key in ('tenant_id', 'collection', 'document_id')}
    physical = dict(fixture['physical'])
    instance = 'instance-fixture'
    intent_id = fixture['intent']['intent_id']
    manifest = json.dumps(fixture['canonical_tuples']['manifest'], ensure_ascii=False, separators=(',', ':')).encode()
    intent_tuple = list(fixture['canonical_tuples']['stage_intent'])
    intent_tuple[7] = None  # This fixture starts with an existing, empty document.
    payload = json.dumps(intent_tuple, ensure_ascii=False, separators=(',', ':')).encode()
    intent = dict(common, intent_id=intent_id, instance_id=instance, action='stage',
        payload_bytes=payload, payload_sha256=sha256(payload).hexdigest(),
        manifest_bytes=manifest, manifest_sha256=sha256(manifest).hexdigest(),
        revision_id=source['revision_id'], generation_id=fixture['intent']['generation_id'],
        expected_active_generation_id=None, expected_authorization_revision=document['authorization_revision'],
        expected_mutation_epoch=document['mutation_epoch'])
    document_row = dict(common, principal_ids=document['principal_ids'], grant_ids=document['grant_ids'],
        authorization_revision=document['authorization_revision'], mutation_epoch=document['mutation_epoch'],
        language=document['language'], kind=document['kind'], tag=document['tag'])
    revision = dict(common, revision_id=source['revision_id'],
        canonical_utf8=source['canonical_utf8']['value'].encode(), source_sha256=source['source_sha256'],
        source_locator=source['source_locator'], parser_id=source['parser_id'])
    generation = dict(common, revision_id=source['revision_id'], generation_id=fixture['intent']['generation_id'],
        **physical, chunker_profile=fixture['intent']['chunker_profile'],
        dense_profile_id=fixture['profiles']['dense']['profile_id'], sparse_profile_id=fixture['profiles']['sparse']['profile_id'],
        dense_profile=fixture['profiles']['dense'], sparse_profile=fixture['profiles']['sparse'], expected_member_count=2)
    members, claims, replays = [], [], []
    for member in fixture['members']:
        member_row = dict(common, revision_id=source['revision_id'], generation_id=generation['generation_id'],
            chunk_id=member['chunk_id'], point_id=member['point_id'], start_byte=member['start_byte'],
            end_byte=member['end_byte'], source_sha256=source['source_sha256'], text_sha256=member['text_sha256'],
            excerpt_utf8=member['excerpt_utf8']['value'].encode())
        members.append(member_row)
        claim = {key: value for key, value in member_row.items() if key != 'excerpt_utf8'}
        claim.update(physical, instance_id=instance, dense_profile=fixture['profiles']['dense'],
            sparse_profile=fixture['profiles']['sparse'], dense_input_sha256=member['dense']['vector_sha256'],
            sparse_input_sha256=member['sparse']['vector_sha256'])
        claims.append(claim)
        dense = [0.0] * 1536
        dense[member['dense']['basis_index']] = member['dense']['value']
        dense_blob = replay_blob('dense', dense)
        sparse_blob = replay_blob('sparse', member['sparse']['values'], member['sparse']['indices'])
        replays.append(dict(common, revision_id=source['revision_id'], generation_id=generation['generation_id'],
            chunk_id=member['chunk_id'], **physical, point_id=member['point_id'],
            dense_blob=dense_blob, dense_blob_sha256=sha256(dense_blob).hexdigest(),
            sparse_blob=sparse_blob, sparse_blob_sha256=sha256(sparse_blob).hexdigest()))
    return dict(backend=dict(instance_id=instance, backend_namespace=physical['backend_namespace'],
        storage_identity='storage-fixture', supervisor_id='supervisor-fixture'), intent=intent,
        document=document_row, revision=revision, generation=generation, members=members, claims=claims, replays=replays)


async def run_probes(connection) -> list[str]:
    """Exercise real constraints and nonowner policies in the caller's transaction."""
    from psycopg import sql

    checks = []
    records = seed_records()
    prefix = 'qw_probe_' + secrets.token_hex(6)
    roles = {kind: prefix + '_' + kind for kind in ('reader', 'writer', 'supervisor')}
    token = '00000000-0000-4000-8000-000000000001'
    common = {key: records['document'][key] for key in ('tenant_id', 'collection', 'document_id')}
    where = ' AND '.join(f'{key}={literal(value)}' for key, value in common.items())
    intent_where = where + ' AND intent_id=' + literal(records['intent']['intent_id'])

    async def command(query, params=None):
        return await connection.execute(query, params, prepare=False)

    async def check(condition, label):
        await command(assert_sql(condition, label))

    async def reject(statement, state='23514'):
        await command(rejected_sql(statement, state))

    async def role(kind):
        await command('RESET ROLE')
        await command(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(roles[kind])))

    async def settings(**changes):
        scope = dict(tenant_id=common['tenant_id'], collection=common['collection'], principal_id='reader-a',
            grant_ids='["grant-a"]', authorization_revision='auth-1', writer_document_id=common['document_id'],
            writer_intent_id=records['intent']['intent_id'], writer_owner_token=token,
            backend_instance_id=records['backend']['instance_id'])
        scope.update(changes)
        for key, value in scope.items():
            await command('SELECT set_config(%s,%s,true)', ('cragkit_qdrant.' + key, value))

    await check("current_setting('transaction_isolation')='read committed'", 'publication_read_committed_required')

    for name in roles.values():
        await command(sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT').format(sql.Identifier(name)))
        await command(sql.SQL('GRANT {} TO CURRENT_USER WITH SET TRUE').format(sql.Identifier(name)))
    for kind, capability in zip(('writer', 'supervisor'), CAPABILITY_ROLES):
        await command(sql.SQL('GRANT {} TO {} WITH INHERIT TRUE, SET FALSE').format(sql.Identifier(capability), sql.Identifier(roles[kind])))
    await command(sql.SQL('GRANT USAGE ON SCHEMA cragkit_qdrant TO {}').format(sql.Identifier(roles['reader'])))
    await command(sql.SQL('GRANT SELECT ON cragkit_qdrant.documents,cragkit_qdrant.document_revisions,cragkit_qdrant.generations,cragkit_qdrant.members,cragkit_qdrant.schema_migrations TO {}').format(sql.Identifier(roles['reader'])))
    await command(sql.SQL('GRANT EXECUTE ON FUNCTION cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean),cragkit_qdrant.scope_grants(),cragkit_qdrant.valid_identity_array(text[]) TO {}').format(sql.Identifier(roles['reader'])))
    await settings()
    await role('supervisor')
    await command(insert_sql('backend_instances', records['backend']))
    await role('writer')
    await command(insert_sql('publication_intents', records['intent']))
    for table, key in [('documents', 'document'), ('document_revisions', 'revision'), ('generations', 'generation')]:
        await command(insert_sql(table, records[key]))
    for key, table in [('members', 'members'), ('claims', 'point_claims'), ('replays', 'vector_replays')]:
        for record in (records[key][:1] if key == 'replays' else records[key]):
            await command(insert_sql(table, record))
    await command('SET CONSTRAINTS ALL IMMEDIATE')
    await command('SET CONSTRAINTS ALL DEFERRED')
    checks.append('writer_scoped_source_stage_and_complete_claim_inserts')

    await role('reader')
    for table in ('document_revisions', 'generations', 'members'):
        await check(f'(SELECT count(*)=0 FROM cragkit_qdrant.{table})', 'reader_staged_' + table + '_hidden')
    await reject("UPDATE cragkit_qdrant.documents SET tag='forbidden';", '42501')
    await reject('SELECT payload_bytes FROM cragkit_qdrant.publication_intents;', '42501')
    checks.append('reader_staged_content_hidden_even_with_all_writer_gucs')

    await role('supervisor')
    for statement in ('SELECT canonical_utf8 FROM cragkit_qdrant.document_revisions;',
        'SELECT payload_bytes FROM cragkit_qdrant.publication_intents;',
        'SELECT manifest_bytes FROM cragkit_qdrant.publication_intents;',
        'SELECT request_bytes FROM cragkit_qdrant.dispatch_journal;',
        'SELECT dense_blob FROM cragkit_qdrant.vector_replays;'):
        await reject(statement, '42501')
    checks.append('supervisor_column_grants_exclude_source_manifest_request_and_vectors')

    await role('writer')
    for table in ('document_revisions', 'generations', 'members'):
        await check(f'(SELECT count(*)>0 FROM cragkit_qdrant.{table})', 'writer_owned_stage_' + table)
    await settings(writer_intent_id='foreign-intent')
    await check('(SELECT count(*)=0 FROM cragkit_qdrant.members)', 'writer_wrong_bound_intent_staged_hidden')
    await settings(tenant_id='foreign-tenant')
    await check('(SELECT count(*)=0 FROM cragkit_qdrant.publication_intents)', 'writer_foreign_tenant_intents_hidden')
    await settings()
    checks.append('writer_stage_requires_exact_scope_and_bound_stage_intent')

    await reject("UPDATE cragkit_qdrant.publication_intents SET payload_sha256=repeat('a',64);")
    await reject('UPDATE cragkit_qdrant.members SET point_id=point_id;')
    for statement in ("UPDATE cragkit_qdrant.point_claims SET chunk_id='changed';",
        "UPDATE cragkit_qdrant.vector_replays SET dense_blob_sha256=repeat('a',64);",
        "UPDATE cragkit_qdrant.document_revisions SET source_locator='changed';"):
        await reject(statement, '42501')
    for table in ('point_claims', 'dispatch_journal', 'publication_intents', 'vector_replays'):
        await reject('DELETE FROM cragkit_qdrant.' + table + ';', '42501')
    checks.append('immutable_content_intent_claim_replay_and_no_retained_fact_delete')

    owner = dict(common, instance_id=records['backend']['instance_id'], intent_id=records['intent']['intent_id'],
        owner_token=token, backend_epoch=1)
    await command(insert_sql('document_owners', owner))
    await command("UPDATE cragkit_qdrant.publication_intents SET state='writing' WHERE " + intent_where)
    preparation = dict(common, intent_id=records['intent']['intent_id'],
        instance_id=records['backend']['instance_id'], owner_token=token, backend_epoch=1,
        authorization_revision='auth-1', mutation_epoch=1,
        manifest_sha256=records['intent']['manifest_sha256'], readback_sha256=sha256(b'synthetic-readback').hexdigest())
    await reject(insert_sql('preparations', preparation))
    await command(insert_sql('vector_replays', records['replays'][1]))
    checks.append('incomplete_replay_membership_cannot_prepare')
    request = b'{"synthetic":"complete-point-write"}'
    dispatch = dict(common, intent_id=records['intent']['intent_id'], dispatch_id='dispatch-1',
        instance_id=records['backend']['instance_id'], sequence=1, owner_token=token, backend_epoch=1,
        credential_generation='credential-epoch-1', operation='complete_point_upsert',
        request_bytes=request, request_sha256=sha256(request).hexdigest())
    await command(insert_sql('dispatch_journal', dispatch))
    for claim in records['claims']:
        point = dict(common, intent_id=records['intent']['intent_id'], dispatch_id='dispatch-1',
            **{key: claim[key] for key in ('backend_namespace', 'physical_collection', 'collection_incarnation', 'point_id')})
        await command(insert_sql('dispatch_points', point))
    await command('SET CONSTRAINTS ALL IMMEDIATE')
    await command('SET CONSTRAINTS ALL DEFERRED')
    # This proves SQL consistency only. The supplied synthetic readback digest
    # is not a claim that an external Qdrant write or verification happened.
    await reject(insert_sql('preparations', preparation))
    await reject("UPDATE cragkit_qdrant.documents SET active_generation_id="
        + literal(records['generation']['generation_id']) + ' WHERE ' + where + '; SET CONSTRAINTS ALL IMMEDIATE;')
    await reject("UPDATE cragkit_qdrant.publication_intents SET state='prepared' WHERE "
        + intent_where + '; SET CONSTRAINTS ALL IMMEDIATE;')
    malformed_preparations = []
    for changes in ({'authorization_revision': 'stale'}, {'mutation_epoch': 0},
        {'manifest_sha256': 'a' * 64}, {'backend_epoch': 2},
        {'owner_token': '00000000-0000-4000-8000-000000000002'}):
        malformed_preparations.append(rejected_block(insert_sql('preparations', preparation | changes)))
    await command(rolled_back_case_sql([
        "UPDATE cragkit_qdrant.dispatch_journal SET state='settled',completion_sha256="
        + literal(sha256(b'synthetic-completion').hexdigest()) + ' WHERE ' + intent_where + ';',
        *malformed_preparations,
        insert_sql('preparations', preparation),
        "UPDATE cragkit_qdrant.publication_intents SET state='prepared' WHERE " + intent_where + ';',
        "UPDATE cragkit_qdrant.documents SET active_generation_id=" + literal(records['generation']['generation_id']) + ' WHERE ' + where + ';',
        'UPDATE cragkit_qdrant.generations SET published=true,ever_published=true WHERE ' + where + ';',
        "UPDATE cragkit_qdrant.publication_intents SET state='published',authority_committed=true,replica_complete=true WHERE " + intent_where + ';',
        'SET CONSTRAINTS ALL IMMEDIATE;',
        "IF NOT EXISTS (SELECT 1 FROM cragkit_qdrant.publication_intents WHERE " + intent_where
        + " AND state='published') THEN RAISE EXCEPTION 'publication_legal_transition_missing'; END IF;",
    ]))
    checks.append('deferred_legal_complete_publication_and_unresolved_preparation_denial')
    await command('SET CONSTRAINTS ALL DEFERRED')
    await settings(writer_owner_token='00000000-0000-4000-8000-000000000002')
    await reject("UPDATE cragkit_qdrant.document_owners SET owner_token='00000000-0000-4000-8000-000000000002' WHERE " + where + ';')
    await settings()
    await reject("UPDATE cragkit_qdrant.dispatch_journal SET request_sha256=repeat('b',64) WHERE " + intent_where + ';')
    await command("UPDATE cragkit_qdrant.dispatch_journal SET state='unknown' WHERE " + intent_where)
    await settings(writer_owner_token='00000000-0000-4000-8000-000000000002')
    await reject("UPDATE cragkit_qdrant.document_owners SET owner_token='00000000-0000-4000-8000-000000000002' WHERE " + where + ';')
    await settings()
    checks.append('reserved_and_unknown_dispatch_block_successor_and_bind_request')

    await settings(writer_intent_id='successor-intent')
    await check('(SELECT count(*)=1 FROM cragkit_qdrant.dispatch_journal WHERE ' + where + ')',
        'writer_sees_all_same_document_predecessor_journal')
    await settings()

    # Deliberately seed a second scoped member with the same physical UUID.
    # SQL's global registry must defend this even if an upstream codec is bypassed.
    foreign = deepcopy(records)
    for name in ('intent', 'document', 'revision', 'generation'):
        foreign[name]['tenant_id'] = 'tenant-foreign'
        foreign[name]['document_id'] = 'doc-foreign'
    foreign['intent']['intent_id'] = 'foreign-intent'
    for rows in ('members', 'claims', 'replays'):
        for row in foreign[rows]:
            row.update(tenant_id='tenant-foreign', document_id='doc-foreign')
    await settings(tenant_id='tenant-foreign', writer_document_id='doc-foreign', writer_intent_id='foreign-intent')
    await command(insert_sql('publication_intents', foreign['intent']))
    for table, key in [('documents', 'document'), ('document_revisions', 'revision'), ('generations', 'generation')]:
        await command(insert_sql(table, foreign[key]))
    for row in foreign['members']:
        await command(insert_sql('members', row))
    await check('(SELECT count(*)=0 FROM cragkit_qdrant.point_claims)', 'foreign_global_claim_owner_hidden')
    collision = insert_sql('point_claims', foreign['claims'][0]).rstrip(';')
    collision += ' ON CONFLICT (backend_namespace,physical_collection,collection_incarnation,point_id) DO NOTHING RETURNING point_id'
    cursor = await command(collision)
    if await cursor.fetchall() != []:
        raise RuntimeError('publication_hidden_global_claim_collision_accepted')
    await reject(collision.split(' ON CONFLICT ')[0] + ' ON CONFLICT (backend_namespace,physical_collection,collection_incarnation,point_id) DO UPDATE SET document_id=EXCLUDED.document_id;', '42501')
    # A second noncolliding foreign claim exists for dispatch-owner checks.
    await command('RESET ROLE')
    foreign_claim = dict(foreign['claims'][1])
    foreign_claim['point_id'] = '00000000-0000-5000-8000-000000000003'
    # Immutable member identity is seeded before insertion, never updated.
    extra_member = dict(foreign['members'][1], chunk_id='foreign-extra', point_id=foreign_claim['point_id'])
    foreign_claim['chunk_id'] = extra_member['chunk_id']
    await command(insert_sql('members', extra_member))
    await command(insert_sql('point_claims', foreign_claim))
    await role('writer')
    foreign_owner = dict(owner, tenant_id='tenant-foreign', document_id='doc-foreign', intent_id='foreign-intent')
    foreign_dispatch = dict(dispatch, tenant_id='tenant-foreign', document_id='doc-foreign', intent_id='foreign-intent')
    cross_point = dict(common, tenant_id='tenant-foreign', document_id='doc-foreign', intent_id='foreign-intent',
        dispatch_id='dispatch-1', **{key: records['claims'][0][key]
        for key in ('backend_namespace', 'physical_collection', 'collection_incarnation', 'point_id')})
    await command(rolled_back_case_sql([
        insert_sql('document_owners', foreign_owner),
        "UPDATE cragkit_qdrant.publication_intents SET state='writing' WHERE tenant_id='tenant-foreign' AND document_id='doc-foreign';",
        insert_sql('dispatch_journal', foreign_dispatch),
        'DECLARE observed boolean := false; BEGIN BEGIN ' + insert_sql('dispatch_points', cross_point)
        + " EXCEPTION WHEN SQLSTATE '23514' THEN observed := true; END; "
        + "IF NOT observed THEN RAISE EXCEPTION 'cross_document_dispatch_point_accepted'; END IF; END;",
    ]))
    await settings()
    await check('(SELECT count(*)=2 FROM cragkit_qdrant.point_claims WHERE ' + where + ')', 'original_global_claim_owners_unchanged')
    checks.append('hidden_cross_tenant_global_uuid_collision_never_overwrites_owner')
    checks.append('reserved_dispatch_cannot_bind_another_documents_global_claim')

    await settings(writer_intent_id='invalid-security')
    invalid_security = dict(records['intent'], intent_id='invalid-security', action='tombstone',
        manifest_bytes=None, manifest_sha256=None, revision_id=None, generation_id=None)
    invalid_security['manifest_sha256'] = records['intent']['manifest_sha256']
    await reject(insert_sql('publication_intents', invalid_security))
    await settings()
    checks.append('nonstage_partial_manifest_fields_rejected')

    await role('supervisor')
    await check('(SELECT count(*)=2 FROM cragkit_qdrant.publication_intents)', 'supervisor_global_nontext_intents_visible')
    await command("UPDATE cragkit_qdrant.backend_instances SET state='recovery_blocked',epoch=epoch+1,recovery_id='recovery-1' WHERE instance_id="
        + literal(records['backend']['instance_id']))
    await reject("UPDATE cragkit_qdrant.backend_instances SET state='open',recovery_id=NULL WHERE instance_id="
        + literal(records['backend']['instance_id']) + ';')
    await role('writer')
    await settings(tenant_id='tenant-foreign', writer_document_id='doc-foreign', writer_intent_id='foreign-intent')
    foreign_owner = dict(owner, tenant_id='tenant-foreign', document_id='doc-foreign', intent_id='foreign-intent', backend_epoch=2)
    await reject(insert_sql('document_owners', foreign_owner))
    await settings()
    await command("UPDATE cragkit_qdrant.documents SET grant_ids='{}'::text[],tag='updated',"
        "authorization_revision='auth-2',mutation_epoch=2 WHERE " + where)
    await settings(authorization_revision='auth-2')
    await role('reader')
    await check('(SELECT count(*)=1 FROM cragkit_qdrant.documents)', 'blocked_recovery_current_authorization_update_visible')
    await role('writer')
    await command("UPDATE cragkit_qdrant.documents SET principal_ids='{}'::text[],"
        "authorization_revision='auth-3',mutation_epoch=3,tombstoned=true WHERE " + where)
    await settings(authorization_revision='auth-3')
    await role('reader')
    for table in ('documents', 'document_revisions', 'generations', 'members'):
        await check(f'(SELECT count(*)=0 FROM cragkit_qdrant.{table})', 'blocked_recovery_tombstone_denies_' + table)
    checks.append('instance_gate_blocks_other_document_while_authoritative_tombstone_commits')

    await role('supervisor')
    recovery = dict(dispatch, dispatch_id='recovery-dispatch-2', sequence=2, backend_epoch=2,
        credential_generation='credential-epoch-2', recovery=True)
    recovery_points = [dict(common, intent_id=records['intent']['intent_id'], dispatch_id=recovery['dispatch_id'],
        **{key: claim[key] for key in ('backend_namespace', 'physical_collection', 'collection_incarnation', 'point_id')})
        for claim in records['claims']]
    completion = literal(sha256(b'synthetic-recovery-completion').hexdigest())
    await command(rolled_back_case_sql([
        'UPDATE cragkit_qdrant.document_owners SET backend_epoch=2 WHERE ' + where + ';',
        "UPDATE cragkit_qdrant.dispatch_journal SET state='settled',completion_sha256=" + completion
        + ' WHERE ' + intent_where + " AND dispatch_id='dispatch-1';",
        insert_sql('dispatch_journal', recovery),
        *[insert_sql('dispatch_points', point) for point in recovery_points],
        'SET CONSTRAINTS ALL IMMEDIATE;',
        "UPDATE cragkit_qdrant.dispatch_journal SET state='settled',completion_sha256=" + completion
        + ' WHERE ' + intent_where + ' AND dispatch_id=' + literal(recovery['dispatch_id']) + ';',
        "UPDATE cragkit_qdrant.backend_instances SET state='open',recovery_id=NULL WHERE instance_id="
        + literal(records['backend']['instance_id']) + ';',
        "IF NOT EXISTS (SELECT 1 FROM cragkit_qdrant.backend_instances WHERE state='open' AND epoch=2) "
        "THEN RAISE EXCEPTION 'publication_recovery_reopen_missing'; END IF;",
        'IF NOT EXISTS (SELECT 1 FROM cragkit_qdrant.dispatch_journal WHERE ' + intent_where
        + " AND dispatch_id='dispatch-1' AND backend_epoch=1 AND state='settled') "
        "THEN RAISE EXCEPTION 'publication_historical_dispatch_rewritten'; END IF;",
    ]))
    checks.append('supervisor_same_owner_epoch_recovery_settles_history_and_reopens_sql_only')

    await command('RESET ROLE')
    await command('SET CONSTRAINTS ALL IMMEDIATE')
    return checks
