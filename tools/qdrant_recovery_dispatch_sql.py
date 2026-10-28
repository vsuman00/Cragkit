"""Rollback-only recovery dispatch permission probes using synthetic SQL metadata.

No request is sent and no opaque native proof or completed HTTP ACK is created.
The caller installs exact migrations and owns the final transaction rollback.
"""
from copy import deepcopy
from hashlib import sha256
import json
import re
import uuid

from qdrant_attestation_schema import (AttestationProbeState, OWNER_OLD, OWNER_CURRENT, _command,
    _intent_where, _role, _settings, _snapshot, _where)
from qdrant_authority_schema import literal
from qdrant_publication_schema import assert_sql, insert_sql, rejected_sql
from runtime_diagnostics import CleanupFailure

CHECKS = (
    'read_committed_exact_three_migration_fixture',
    'supervisor_blocks_backend_and_advances_same_owner',
    'writer_recovery_insert_denied_under_same_tuple',
    'supervisor_reserves_recovery_journal_and_exact_claim_membership',
    'supervisor_reads_metadata_hash_but_not_request_bytes',
    'supervisor_marks_dispatched_with_fixed_identity',
    'supervisor_sql_synthetic_completion_can_settle_recovery_dispatch',
    'supervisor_cannot_change_request_identity_or_settled_outcome',
    'supervisor_cannot_read_source_revision_or_vector_replay',
    'source_generation_original_preparation_preserved',
)
PROOF_SCOPE = 'recovery_dispatch_sql_synthetic_metadata_only'
SECURITY_CHECKS = (
    'read_committed_exact_three_migration_security_fixture',
    'writer_seeds_second_claimed_generation',
    'authority_security_commit_denies_old_owner_intent',
    'supervisor_blocks_backend_advances_same_denied_owner',
    'writer_and_nonrecovery_dispatch_denied',
    'wrong_owner_epoch_dispatch_denied',
    'supervisor_reserves_denied_owner_cross_generation_membership',
    'unclaimed_and_foreign_physical_membership_denied',
    'premature_security_owner_takeover_denied',
    'supervisor_reads_metadata_not_source_vector_request_bytes',
    'supervisor_synthetic_sql_dispatch_settlement_only',
    'original_source_generation_preparation_preserved',
    'savepoint_security_claims_owner_journals_restored',
)
SECURITY_PROOF_SCOPE = 'security_owner_recovery_sql_synthetic_metadata_only'


def _security_second_generation(state):
    """Keep source/vector seals while deriving a distinct synthetic generation."""
    records = deepcopy(state.records)
    generation = 'g2-security-sql-second-generation'
    intent_id = 'g2-security-sql-second-stage'
    manifest = json.loads(records['intent']['manifest_bytes'].decode('utf-8'))
    manifest[8] = generation
    ids = {}
    for member in manifest[17]:
        member[0][8] = generation
        member[1] = str(uuid.uuid5(uuid.NAMESPACE_URL,json.dumps(member[0],ensure_ascii=False,separators=(',',':'))))
        ids[member[0][9]] = member[1]
    manifest_bytes = json.dumps(manifest,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    digest = sha256(manifest_bytes).hexdigest()
    payload = json.loads(records['intent']['payload_bytes'].decode('utf-8'))
    payload[2],payload[6] = intent_id,digest
    payload_bytes = json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    records['intent'].update(intent_id=intent_id,generation_id=generation,manifest_bytes=manifest_bytes,
        manifest_sha256=digest,payload_bytes=payload_bytes,payload_sha256=sha256(payload_bytes).hexdigest())
    records['generation']['generation_id'] = generation
    for table in ('members','claims','replays'):
        for row in records[table]:
            row.update(generation_id=generation,point_id=ids[row['chunk_id']])
    return records


async def _original_generation_snapshot(connection, state):
    """Scope the old snapshot explicitly; the document now has two generations."""
    records = state.records
    where = _where(records)
    revision = ' AND revision_id=' + literal(records['generation']['revision_id'])
    generation = revision + ' AND generation_id=' + literal(records['generation']['generation_id'])
    cursor = await _command(connection,'SELECT '
        '(SELECT encode(canonical_utf8,\'hex\') FROM cragkit_qdrant.document_revisions WHERE '+where+revision+'),'
        '(SELECT to_jsonb(g)::text FROM cragkit_qdrant.generations g WHERE '+where+generation+'),'
        '(SELECT to_jsonb(p)::text FROM cragkit_qdrant.preparations p WHERE '+_intent_where(records)+')')
    result = tuple(tuple(row) for row in await cursor.fetchall())
    if len(result) != 1 or len(result[0]) != 3 or any(value is None for value in result[0]):
        raise RuntimeError('security_recovery_original_fixture_missing')
    return result


async def _security_inventory_snapshot(connection, state):
    """Return a private digest covering every scoped fact the savepoint touches."""
    parts = []
    for table in ('documents','document_revisions','generations','members','publication_intents','document_owners',
                  'point_claims','vector_replays','dispatch_journal','dispatch_points','preparations','preparation_attestations'):
        parts.extend((literal(table),'(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY to_jsonb(r)::text),\'[]\'::jsonb) '
            'FROM cragkit_qdrant.'+table+' r WHERE '+_where(state.records)+')'))
    parts.extend((literal('backend_instances'),'(SELECT to_jsonb(b) FROM cragkit_qdrant.backend_instances b WHERE instance_id='
                  +literal(state.records['backend']['instance_id'])+')'))
    cursor = await _command(connection,"SELECT encode(sha256(convert_to(jsonb_build_object("+','.join(parts)+")::text,'UTF8')),'hex')")
    rows = await cursor.fetchall()
    if (len(rows) != 1 or len(rows[0]) != 1 or type(rows[0][0]) is not str
            or re.fullmatch('[0-9a-f]{64}',rows[0][0]) is None):
        raise RuntimeError('security_recovery_inventory_shape')
    return rows[0][0]


def recovery_record(state: AttestationProbeState, **changes):
    """Build a bounded, explicitly non-HTTP recovery journal fixture."""
    if type(state) is not AttestationProbeState:
        raise ValueError('recovery_dispatch_probe_state')
    records = state.records
    request = b'{"synthetic_sql_only":"recovery_dispatch_permission_probe"}'
    row = dict((key, records['document'][key]) for key in ('tenant_id', 'collection', 'document_id'))
    row.update(intent_id=records['intent']['intent_id'], dispatch_id='g1b-sql-recovery',
        instance_id=records['backend']['instance_id'], sequence=2, owner_token=OWNER_OLD,
        backend_epoch=2, credential_generation='synthetic-sql-recovery-credential-2',
        operation='complete_point_upsert', recovery=True, request_bytes=request,
        request_sha256=sha256(request).hexdigest())
    if set(changes) - set(row):
        raise ValueError('recovery_dispatch_probe_field')
    row.update(changes)
    return row


async def run_probes(connection, state: AttestationProbeState) -> list[str]:
    """Exercise real role/constraint mechanics inside one rollback savepoint."""
    if type(state) is not AttestationProbeState or not state.legacy_snapshot:
        raise ValueError('recovery_dispatch_probe_preupgrade_state')
    claims = state.records['claims']
    if not 1 <= len(claims) <= 8 or len({claim['point_id'] for claim in claims}) != len(claims):
        raise ValueError('recovery_dispatch_probe_membership_bound')
    checks = []
    row = recovery_record(state)
    where = _where(state.records)
    intent_where = _intent_where(state.records)
    journal_where = intent_where + ' AND dispatch_id=' + literal(row['dispatch_id'])
    backend_where = 'instance_id=' + literal(row['instance_id'])
    completion = sha256(b'G1b SQL-only synthetic completion, no HTTP acknowledgment').hexdigest()

    async def command(query):
        return await _command(connection, query)

    async def check(condition, label):
        await command(assert_sql(condition, label))

    async def reject(statement, code):
        await command(rejected_sql(statement.rstrip(';') + ';', code))

    await command('SAVEPOINT qa_recovery_dispatch')
    primary = None
    try:
        await _role(connection, state, 'admin')
        await check("current_setting('transaction_isolation')='read committed'", 'recovery_dispatch_read_committed')
        await check('(SELECT count(*)=3 FROM cragkit_qdrant.schema_migrations)', 'recovery_dispatch_three_migrations')
        checks.append(CHECKS[0])
        await _settings(connection, state, writer_owner_token=OWNER_OLD)
        await _role(connection, state, 'supervisor')
        await command("UPDATE cragkit_qdrant.backend_instances SET state='recovery_blocked',epoch=2,recovery_id='g1b-sql-recovery' WHERE " + backend_where)
        await command('UPDATE cragkit_qdrant.document_owners SET backend_epoch=2 WHERE ' + where)
        await check("(SELECT state='recovery_blocked' AND epoch=2 AND recovery_id='g1b-sql-recovery' FROM cragkit_qdrant.backend_instances WHERE " + backend_where + ')', 'recovery_dispatch_blocked')
        await check('(SELECT backend_epoch=2 AND owner_token=' + literal(OWNER_OLD)
            + '::uuid AND intent_id=' + literal(row['intent_id']) + ' FROM cragkit_qdrant.document_owners WHERE ' + where + ')', 'recovery_dispatch_same_owner')
        checks.append(CHECKS[1])

        await _role(connection, state, 'writer')
        await reject(insert_sql('dispatch_journal', row), '23514')
        checks.append(CHECKS[2])
        await _role(connection, state, 'supervisor')
        await command(insert_sql('dispatch_journal', row))
        for claim in claims:
            point = {key: row[key] for key in ('tenant_id', 'collection', 'document_id', 'intent_id', 'dispatch_id')}
            point.update({key: claim[key] for key in ('backend_namespace', 'physical_collection', 'collection_incarnation', 'point_id')})
            await command(insert_sql('dispatch_points', point))
        # Deferred events are checked inside the same transaction. This is not
        # a separate COMMIT or evidence of a native physical recovery.
        await command('SET CONSTRAINTS ALL IMMEDIATE')
        await command('SET CONSTRAINTS ALL DEFERRED')
        await check('(SELECT count(*)=' + str(len(claims)) + ' FROM cragkit_qdrant.dispatch_points WHERE ' + journal_where + ')', 'recovery_dispatch_exact_membership_count')
        ids = ','.join(literal(claim['point_id']) + '::uuid' for claim in claims)
        await check('(SELECT bool_and(point_id=ANY(ARRAY[' + ids + '])) FROM cragkit_qdrant.dispatch_points WHERE ' + journal_where + ')', 'recovery_dispatch_exact_claims')
        checks.append(CHECKS[3])

        await check('(SELECT recovery AND state=\'reserved\' AND backend_epoch=2 AND request_sha256='
            + literal(row['request_sha256']) + ' FROM cragkit_qdrant.dispatch_journal WHERE ' + journal_where + ')', 'recovery_dispatch_metadata_hash')
        await reject('SELECT request_bytes FROM cragkit_qdrant.dispatch_journal WHERE ' + journal_where, '42501')
        checks.append(CHECKS[4])
        await command("UPDATE cragkit_qdrant.dispatch_journal SET state='dispatched' WHERE " + journal_where)
        await check("(SELECT state='dispatched' AND completion_sha256 IS NULL FROM cragkit_qdrant.dispatch_journal WHERE " + journal_where + ')', 'recovery_dispatch_dispatched')
        checks.append(CHECKS[5])
        await command("UPDATE cragkit_qdrant.dispatch_journal SET state='settled',completion_sha256=" + literal(completion) + ' WHERE ' + journal_where)
        await check("(SELECT state='settled' AND completion_sha256=" + literal(completion)
            + ' FROM cragkit_qdrant.dispatch_journal WHERE ' + journal_where + ')', 'recovery_dispatch_synthetic_settled')
        checks.append(CHECKS[6])
        await reject('UPDATE cragkit_qdrant.dispatch_journal SET request_sha256=' + literal('a'*64) + ' WHERE ' + journal_where, '42501')
        await reject("UPDATE cragkit_qdrant.dispatch_journal SET state='dispatched',completion_sha256=NULL WHERE " + journal_where, '23514')
        checks.append(CHECKS[7])
        for table, column in (('document_revisions', 'canonical_utf8'), ('vector_replays', 'dense_blob')):
            await reject('SELECT ' + column + ' FROM cragkit_qdrant.' + table + ' WHERE ' + where, '42501')
        checks.append(CHECKS[8])
        await _role(connection, state, 'admin')
        if await _snapshot(connection, state) != state.legacy_snapshot:
            raise RuntimeError('recovery_dispatch_changed_legacy_facts')
        checks.append(CHECKS[9])
        return checks
    except BaseException as error:
        primary = error
        raise
    finally:
        failures = []
        for operation, query in (('probe_rollback', 'ROLLBACK TO SAVEPOINT qa_recovery_dispatch'),
                ('probe_release', 'RELEASE SAVEPOINT qa_recovery_dispatch'), ('probe_reset_role', 'RESET ROLE')):
            try:
                await command(query)
            except BaseException as error:
                failures.append((operation, error))
        if failures:
            raise CleanupFailure(failures, primary=primary, stage='fixture_setup') from None


async def run_security_probes(connection, state: AttestationProbeState) -> list[str]:
    """Prove denied-owner SQL permissions; all completion metadata is synthetic."""
    if type(state) is not AttestationProbeState or not state.legacy_snapshot:
        raise ValueError('security_recovery_probe_preupgrade_state')
    claims = state.records['claims']
    if not 1 <= len(claims) <= 4 or len({claim['point_id'] for claim in claims}) != len(claims):
        raise ValueError('security_recovery_probe_membership_bound')
    second = _security_second_generation(state)
    all_claims = claims + second['claims']
    if len({claim['point_id'] for claim in all_claims}) != len(all_claims):
        raise ValueError('security_recovery_probe_generation_identity')
    records = state.records
    where,intent_where = _where(records),_intent_where(records)
    row = recovery_record(state,dispatch_id='g2-security-sql-recovery')
    journal_where = intent_where+' AND dispatch_id='+literal(row['dispatch_id'])
    backend_where = 'instance_id='+literal(row['instance_id'])
    security_id = 'g2-security-sql-authority'
    common = {key:records['document'][key] for key in ('tenant_id','collection','document_id')}
    security_where = where+' AND intent_id='+literal(security_id)
    authorization = ['auth-2',[],[],None,None,None,'false']
    payload = json.dumps(['cragkit.qdrant.intent.v1','update_authorization',security_id,
        *common.values(),'auth-1','1',authorization],ensure_ascii=False,separators=(',',':')).encode('utf-8')
    security = dict(common,intent_id=security_id,instance_id=row['instance_id'],action='update_authorization',
        payload_bytes=payload,payload_sha256=sha256(payload).hexdigest(),
        expected_authorization_revision='auth-1',expected_mutation_epoch=1)
    completion = sha256(b'G2 SQL-only synthetic completion; no HTTP ACK or physical proof').hexdigest()
    checks = []
    initial = None
    async def command(query):return await _command(connection,query)
    async def check(condition,label):await command(assert_sql(condition,label))
    async def reject(statement,code='23514'):
        await command(rejected_sql(statement.rstrip(';')+';',code))
    def point(claim):
        return dict(common,intent_id=row['intent_id'],dispatch_id=row['dispatch_id'],
            **{key:claim[key] for key in ('backend_namespace','physical_collection','collection_incarnation','point_id')})

    await command('SAVEPOINT qa_security_owner_recovery')
    primary = None
    try:
        await _role(connection,state,'admin')
        initial = await _security_inventory_snapshot(connection,state)
        await check("current_setting('transaction_isolation')='read committed'",'security_recovery_read_committed')
        await check('(SELECT count(*)=3 FROM cragkit_qdrant.schema_migrations)','security_recovery_three_migrations')
        checks.append(SECURITY_CHECKS[0])
        await _settings(connection,state,writer_intent_id=second['intent']['intent_id'],writer_owner_token=OWNER_OLD)
        await _role(connection,state,'writer')
        await command(insert_sql('publication_intents',second['intent']))
        await command(insert_sql('generations',second['generation']))
        for table,key in (('members','members'),('point_claims','claims'),('vector_replays','replays')):
            for item in second[key]:await command(insert_sql(table,item))
        await command('SET CONSTRAINTS ALL IMMEDIATE')
        await command('SET CONSTRAINTS ALL DEFERRED')
        await check('(SELECT count(*)='+str(len(all_claims))+' FROM cragkit_qdrant.point_claims WHERE '+where+')',
                    'security_recovery_both_generations_claimed')
        checks.append(SECURITY_CHECKS[1])

        await _settings(connection,state,writer_intent_id=security_id,writer_owner_token=OWNER_OLD)
        await command(insert_sql('publication_intents',security))
        await command("UPDATE cragkit_qdrant.documents SET authorization_revision='auth-2',mutation_epoch=2,"
            "principal_ids=ARRAY[]::text[],grant_ids=ARRAY[]::text[],language=NULL,kind=NULL,tag=NULL WHERE "+where)
        await command("UPDATE cragkit_qdrant.publication_intents SET state='authority_committed',authority_committed=true WHERE "+security_where)
        await _settings(connection,state,writer_owner_token=OWNER_OLD,authorization_revision='auth-2')
        await command("UPDATE cragkit_qdrant.publication_intents SET state='denied' WHERE "+intent_where)
        await command('SET CONSTRAINTS ALL IMMEDIATE')
        await command('SET CONSTRAINTS ALL DEFERRED')
        await check("(SELECT authorization_revision='auth-2' AND mutation_epoch=2 AND principal_ids=ARRAY[]::text[] "
            'AND grant_ids=ARRAY[]::text[] FROM cragkit_qdrant.documents WHERE '+where+')','security_recovery_authority_committed')
        await check("(SELECT state='denied' FROM cragkit_qdrant.publication_intents WHERE "+intent_where+')',
                    'security_recovery_old_owner_denied')
        checks.append(SECURITY_CHECKS[2])

        await _role(connection,state,'supervisor')
        await command("UPDATE cragkit_qdrant.backend_instances SET state='recovery_blocked',epoch=2,recovery_id='g2-security-sql-recovery' WHERE "+backend_where)
        await command('UPDATE cragkit_qdrant.document_owners SET backend_epoch=2 WHERE '+where)
        await check('(SELECT backend_epoch=2 AND owner_token='+literal(OWNER_OLD)+'::uuid AND intent_id='
            +literal(row['intent_id'])+' FROM cragkit_qdrant.document_owners WHERE '+where+')','security_recovery_same_denied_owner')
        checks.append(SECURITY_CHECKS[3])
        await _role(connection,state,'writer')
        await reject(insert_sql('dispatch_journal',row))
        await reject(insert_sql('dispatch_journal',dict(row,recovery=False,dispatch_id='g2-security-sql-ordinary')))
        await _role(connection,state,'supervisor')
        await reject(insert_sql('dispatch_journal',dict(row,recovery=False,dispatch_id='g2-security-sql-supervisor-ordinary')))
        checks.append(SECURITY_CHECKS[4])
        for change in (dict(owner_token=OWNER_CURRENT),dict(backend_epoch=1),dict(backend_epoch=3),
                       dict(intent_id=security_id)):
            await reject(insert_sql('dispatch_journal',dict(row,**change)))
        checks.append(SECURITY_CHECKS[5])

        await command(insert_sql('dispatch_journal',row))
        for claim in all_claims:await command(insert_sql('dispatch_points',point(claim)))
        await command('SET CONSTRAINTS ALL IMMEDIATE')
        await command('SET CONSTRAINTS ALL DEFERRED')
        ids = ','.join(literal(claim['point_id'])+'::uuid' for claim in all_claims)
        await check('(SELECT count(*)='+str(len(all_claims))+' AND bool_and(point_id=ANY(ARRAY['+ids+
            '])) FROM cragkit_qdrant.dispatch_points WHERE '+journal_where+')','security_recovery_exact_cross_generation_membership')
        checks.append(SECURITY_CHECKS[6])
        for changed in (dict(point_id='00000000-0000-4000-8000-000000000099'),
                        dict(physical_collection='foreign_physical_collection'),dict(collection_incarnation='foreign-incarnation')):
            await reject(insert_sql('dispatch_points',dict(point(claims[0]),**changed)))
        checks.append(SECURITY_CHECKS[7])

        await reject('UPDATE cragkit_qdrant.document_owners SET owner_token='+literal(OWNER_CURRENT)+'::uuid,intent_id='
            +literal(security_id)+' WHERE '+where,'42501')
        await _settings(connection,state,writer_intent_id=security_id,writer_owner_token=OWNER_CURRENT,authorization_revision='auth-2')
        await _role(connection,state,'writer')
        await reject('UPDATE cragkit_qdrant.document_owners SET owner_token='+literal(OWNER_CURRENT)+'::uuid,intent_id='
            +literal(security_id)+' WHERE '+where)
        checks.append(SECURITY_CHECKS[8])
        await _settings(connection,state,writer_owner_token=OWNER_OLD,authorization_revision='auth-2')
        await _role(connection,state,'supervisor')
        await check("(SELECT recovery AND state='reserved' AND request_sha256="+literal(row['request_sha256'])+
            ' FROM cragkit_qdrant.dispatch_journal WHERE '+journal_where+')','security_recovery_metadata_hash_only')
        for table,column in (('dispatch_journal','request_bytes'),('publication_intents','payload_bytes'),
                             ('document_revisions','canonical_utf8'),('vector_replays','dense_blob')):
            await reject('SELECT '+column+' FROM cragkit_qdrant.'+table+' WHERE '+where,'42501')
        checks.append(SECURITY_CHECKS[9])
        await command("UPDATE cragkit_qdrant.dispatch_journal SET state='dispatched' WHERE "+journal_where)
        await command("UPDATE cragkit_qdrant.dispatch_journal SET state='settled',completion_sha256="+literal(completion)+' WHERE '+journal_where)
        await check("(SELECT state='settled' AND completion_sha256="+literal(completion)+' FROM cragkit_qdrant.dispatch_journal WHERE '+journal_where+')',
                    'security_recovery_synthetic_sql_completion_only')
        await reject("UPDATE cragkit_qdrant.dispatch_journal SET state='dispatched',completion_sha256=NULL WHERE "+journal_where)
        await command('SET CONSTRAINTS ALL IMMEDIATE')
        await command('SET CONSTRAINTS ALL DEFERRED')
        checks.append(SECURITY_CHECKS[10])
        await _role(connection,state,'admin')
        if await _original_generation_snapshot(connection,state) != state.legacy_snapshot:
            raise RuntimeError('security_recovery_changed_original_facts')
        checks.append(SECURITY_CHECKS[11])
    except BaseException as error:
        primary = error
        raise
    finally:
        failures = []
        for operation,query in (('probe_rollback','ROLLBACK TO SAVEPOINT qa_security_owner_recovery'),
                                ('probe_release','RELEASE SAVEPOINT qa_security_owner_recovery'),('probe_reset_role','RESET ROLE')):
            try:await command(query)
            except BaseException as error:failures.append((operation,error))
        if not failures and initial is not None:
            try:
                if await _security_inventory_snapshot(connection,state) != initial:
                    raise RuntimeError('security_recovery_savepoint_inventory_changed')
            except BaseException as error:failures.append(('verify_inventory',error))
        if failures:raise CleanupFailure(failures,primary=primary,stage='fixture_setup') from None
    checks.append(SECURITY_CHECKS[12])
    return checks
