"""Rollback-only administrative G0-r1 metadata probes, never physical readback proof.

The caller owns the connection, outer transaction, migration application and final
rollback. All completion/readback digests below are synthetic SQL fixture data.
"""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import secrets

from qdrant_authority_schema import ROOT, literal
from qdrant_publication_schema import (PublicationMigration, DELIMITER, assert_sql,
    insert_sql, rejected_sql, seed_records)
from runtime_diagnostics import CleanupFailure

MIGRATION = ROOT / 'storage/qdrant/postgres/migrations/0003_preparation_attestations.sql'
ATTESTATION_COLUMNS = ('tenant_id', 'collection', 'document_id', 'intent_id', 'instance_id',
    'owner_token', 'backend_epoch', 'authorization_revision', 'mutation_epoch', 'manifest_sha256',
    'expected_active_generation_id', 'credential_generation', 'verification_id', 'readback_sha256')
ATTESTATION_KEY = ('tenant_id', 'collection', 'document_id', 'intent_id', 'backend_epoch', 'owner_token')
OWNER_OLD = '00000000-0000-4000-8000-000000000001'
OWNER_CURRENT = '00000000-0000-4000-8000-000000000002'
CHECKS = (
    'read_committed_and_exact_attestation_catalog',
    'preupgrade_prepared_source_generation_preparation_preserved',
    'writer_only_select_insert_no_reader_supervisor_public_privileges',
    'prepared_old_epoch_cannot_publish_without_current_attestation',
    'attestation_exact_owner_epoch_instance_manifest_security_pointer_fences',
    'blocked_unprepared_unsettled_tombstoned_changed_security_pointer_denied',
    'incomplete_members_claims_replays_deny_attestation',
    'wrong_scope_intent_and_instance_attestations_hidden',
    'current_epoch_attestation_exact_key_duplicate_conflicts',
    'attestation_update_delete_immutable_even_for_admin',
    'final_cas_ignores_other_owner_and_epoch_rows',
    'final_cas_requires_exact_current_tuple_not_maximum',
    'current_epoch_exact_attestation_publishes_same_intent_generation',
    'original_preparation_unchanged_after_attested_publication_probe',
)


def migration(path: Path = MIGRATION) -> PublicationMigration:
    """Read exact additive bytes; applying/recording them remains administrative."""
    if path.name != MIGRATION.name:
        raise ValueError('attestation_migration_identity')
    with path.open('rb') as source_file:
        raw = source_file.read(1048577)
    if not 1 <= len(raw) <= 1048576:
        raise ValueError('attestation_migration_size')
    source = raw.decode('utf-8')
    if '\r' in source or re.search(r'(?mi)^\s*(?:COMMIT|ROLLBACK|BEGIN\s*;|\\)', source):
        raise ValueError('attestation_transaction_boundary')
    if DELIMITER in source:
        raise ValueError('attestation_probe_delimiter')
    return PublicationMigration(path.stem, sha256(raw).hexdigest(), source)


@dataclass(frozen=True)
class AttestationProbeState:
    """Private synthetic fixture context; never emit source or SQL to reports."""
    records: dict
    roles: dict
    legacy_snapshot: tuple


async def _command(connection, query, params=None):
    return await connection.execute(query, params, prepare=False)


async def _rows(connection, query):
    return tuple(tuple(row) for row in await (await _command(connection, query)).fetchall())


def _where(records):
    return ' AND '.join(key + '=' + literal(records['document'][key])
                        for key in ('tenant_id', 'collection', 'document_id'))


def _intent_where(records):
    return _where(records) + ' AND intent_id=' + literal(records['intent']['intent_id'])


async def _role(connection, state, kind):
    await _command(connection, 'RESET ROLE')
    if kind != 'admin':
        name = state.roles[kind]
        if re.fullmatch(r'qa_probe_[0-9a-f]{12}_(?:writer|reader|supervisor)', name) is None:
            raise ValueError('attestation_probe_role')
        await _command(connection, 'SET LOCAL ROLE ' + name)


async def _settings(connection, state, **changes):
    records = state.records
    values = dict(tenant_id=records['document']['tenant_id'], collection=records['document']['collection'],
        principal_id='reader-a', grant_ids='["grant-a"]', authorization_revision='auth-1',
        writer_document_id=records['document']['document_id'], writer_intent_id=records['intent']['intent_id'],
        writer_owner_token=OWNER_OLD, backend_instance_id=records['backend']['instance_id'])
    values.update(changes)
    for key, value in values.items():
        await _command(connection, 'SELECT set_config(%s,%s,true)', ('cragkit_qdrant.' + key, value))


async def _snapshot(connection, state):
    where = _where(state.records)
    result = await _rows(connection, 'SELECT '
        '(SELECT encode(canonical_utf8,\'hex\') FROM cragkit_qdrant.document_revisions WHERE ' + where + '),'
        '(SELECT to_jsonb(g)::text FROM cragkit_qdrant.generations g WHERE ' + where + '),'
        '(SELECT to_jsonb(p)::text FROM cragkit_qdrant.preparations p WHERE ' + _intent_where(state.records) + ')')
    if len(result) != 1 or any(value is None for value in result[0]):
        raise RuntimeError('attestation_legacy_fixture_missing')
    return result


async def seed_pre_upgrade(connection) -> AttestationProbeState:
    """Seed real prepared facts under 0001+0002 before the caller applies 0003."""
    await _command(connection, assert_sql("current_setting('transaction_isolation')='read committed'",
                                        'attestation_read_committed_required'))
    records = seed_records()
    prefix = 'qa_probe_' + secrets.token_hex(6)
    roles = {kind: prefix + '_' + kind for kind in ('writer', 'reader', 'supervisor')}
    state = AttestationProbeState(records, roles, ())
    for name in roles.values():
        await _command(connection, 'CREATE ROLE ' + name
            + ' NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT')
        await _command(connection, 'GRANT ' + name + ' TO CURRENT_USER WITH SET TRUE')
    for kind in ('writer', 'supervisor'):
        await _command(connection, 'GRANT cragkit_qdrant_' + kind + ' TO ' + roles[kind]
            + ' WITH INHERIT TRUE, SET FALSE')
    await _command(connection, 'GRANT USAGE ON SCHEMA cragkit_qdrant TO ' + roles['reader'])
    await _command(connection, 'GRANT SELECT ON cragkit_qdrant.documents,cragkit_qdrant.document_revisions,'
        'cragkit_qdrant.generations,cragkit_qdrant.members,cragkit_qdrant.schema_migrations TO ' + roles['reader'])
    await _command(connection, 'GRANT EXECUTE ON FUNCTION '
        'cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean),'
        'cragkit_qdrant.scope_grants(),cragkit_qdrant.valid_identity_array(text[]) TO ' + roles['reader'])
    await _settings(connection, state)
    await _role(connection, state, 'supervisor')
    await _command(connection, insert_sql('backend_instances', records['backend']))
    await _role(connection, state, 'writer')
    await _command(connection, insert_sql('publication_intents', records['intent']))
    for table, key in [('documents', 'document'), ('document_revisions', 'revision'), ('generations', 'generation')]:
        await _command(connection, insert_sql(table, records[key]))
    for table, key in [('members', 'members'), ('point_claims', 'claims'), ('vector_replays', 'replays')]:
        for row in records[key]:
            await _command(connection, insert_sql(table, row))
    common = {key: records['document'][key] for key in ('tenant_id', 'collection', 'document_id')}
    owner = dict(common, instance_id=records['backend']['instance_id'], intent_id=records['intent']['intent_id'],
                 owner_token=OWNER_OLD, backend_epoch=1)
    await _command(connection, insert_sql('document_owners', owner))
    await _command(connection, "UPDATE cragkit_qdrant.publication_intents SET state='writing' WHERE " + _intent_where(records))
    request = b'{"synthetic_sql_only":"attestation_fixture"}'
    dispatch = dict(common, intent_id=records['intent']['intent_id'], dispatch_id='attestation-sql-original',
        instance_id=records['backend']['instance_id'], sequence=1, owner_token=OWNER_OLD, backend_epoch=1,
        credential_generation='synthetic-sql-credential-1', operation='complete_point_upsert',
        request_bytes=request, request_sha256=sha256(request).hexdigest())
    await _command(connection, insert_sql('dispatch_journal', dispatch))
    for claim in records['claims']:
        await _command(connection, insert_sql('dispatch_points', dict(common,
            intent_id=records['intent']['intent_id'], dispatch_id=dispatch['dispatch_id'],
            **{key: claim[key] for key in ('backend_namespace', 'physical_collection', 'collection_incarnation', 'point_id')})))
    await _command(connection, 'SET CONSTRAINTS ALL IMMEDIATE')
    await _command(connection, 'SET CONSTRAINTS ALL DEFERRED')
    # These labeled synthetic digests establish SQL metadata consistency only.
    await _command(connection, "UPDATE cragkit_qdrant.dispatch_journal SET state='settled',completion_sha256="
        + literal(sha256(b'G0 SQL-only synthetic completion').hexdigest()) + ' WHERE ' + _intent_where(records))
    preparation = dict(common, intent_id=records['intent']['intent_id'], instance_id=records['backend']['instance_id'],
        owner_token=OWNER_OLD, backend_epoch=1, authorization_revision='auth-1', mutation_epoch=1,
        manifest_sha256=records['intent']['manifest_sha256'],
        readback_sha256=sha256(b'G0 SQL-only synthetic original readback').hexdigest())
    await _command(connection, insert_sql('preparations', preparation))
    await _command(connection, "UPDATE cragkit_qdrant.publication_intents SET state='prepared' WHERE " + _intent_where(records))
    await _command(connection, 'SET CONSTRAINTS ALL IMMEDIATE')
    await _command(connection, 'SET CONSTRAINTS ALL DEFERRED')
    await _role(connection, state, 'admin')
    return AttestationProbeState(records, roles, await _snapshot(connection, state))


def attestation_record(state, **changes):
    """Construct the exact14 synthetic SQL-only tuple, never a receipt."""
    records = state.records
    row = {key: records['document'][key] for key in ('tenant_id', 'collection', 'document_id')}
    row.update(intent_id=records['intent']['intent_id'], instance_id=records['backend']['instance_id'],
        owner_token=OWNER_CURRENT, backend_epoch=2, authorization_revision='auth-1', mutation_epoch=1,
        manifest_sha256=records['intent']['manifest_sha256'], expected_active_generation_id=None,
        credential_generation='synthetic-sql-credential-2', verification_id='synthetic-sql-verification-2',
        readback_sha256=sha256(b'G0 SQL-only synthetic current readback').hexdigest())
    if set(changes) - set(ATTESTATION_COLUMNS):
        raise ValueError('attestation_probe_field')
    row.update(changes)
    return {key: row[key] for key in ATTESTATION_COLUMNS}


async def run_probes(connection, state: AttestationProbeState) -> list[str]:
    """Run actual PostgreSQL checks under the caller's mandatory final rollback."""
    if type(state) is not AttestationProbeState or not state.legacy_snapshot:
        raise ValueError('attestation_probe_preupgrade_state')
    checks = []
    records = state.records
    where, intent_where = _where(records), _intent_where(records)
    async def command(query):
        return await _command(connection, query)
    async def check(condition, label):
        await command(assert_sql(condition, label))
    async def reject(statement, code='23514'):
        if not statement.rstrip().endswith(';'):
            statement += ';'
        await command(rejected_sql(statement, code))
    async def role(kind):
        await _role(connection, state, kind)
    async def settings(**changes):
        await _settings(connection, state, writer_owner_token=changes.pop('writer_owner_token', OWNER_CURRENT), **changes)
    async def case(steps):
        await command('SAVEPOINT qa_case')
        primary = None
        try:
            for statement in steps:
                await command(statement)
        except BaseException as error:
            primary = error
            raise
        finally:
            failures = []
            for operation, statement in (('probe_rollback', 'ROLLBACK TO SAVEPOINT qa_case'),
                    ('probe_release', 'RELEASE SAVEPOINT qa_case')):
                try:
                    await command(statement)
                except BaseException as error:
                    failures.append((operation, error))
            if failures:
                raise CleanupFailure(failures, primary=primary, stage='fixture_setup') from None
    def fault(table, statement):
        # Admin-only fault injection; never ordinary evidence or runtime repair.
        # Flush valid deferred events before ALTER TABLE, including FK events
        # queued by the injected mutation; restore deferred publication CAS.
        return ['SET CONSTRAINTS ALL IMMEDIATE;',
                f'ALTER TABLE cragkit_qdrant.{table} DISABLE TRIGGER USER;', statement,
                'SET CONSTRAINTS ALL IMMEDIATE;',
                f'ALTER TABLE cragkit_qdrant.{table} ENABLE TRIGGER USER;',
                'SET CONSTRAINTS ALL DEFERRED;']
    def final_cas():
        return ["UPDATE cragkit_qdrant.documents SET active_generation_id=" + literal(records['generation']['generation_id']) + ' WHERE ' + where + ';',
            'UPDATE cragkit_qdrant.generations SET published=true,ever_published=true WHERE ' + where + ';',
            "UPDATE cragkit_qdrant.publication_intents SET state='published',authority_committed=true,replica_complete=true WHERE " + intent_where + ';',
            'SET CONSTRAINTS ALL IMMEDIATE;']
    await role('admin')
    await check("current_setting('transaction_isolation')='read committed'", 'attestation_read_committed_required')
    await check("(SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='cragkit_qdrant.preparation_attestations'::regclass)", 'attestation_forced_rls')
    columns = 'ARRAY[' + ','.join(literal(column) for column in ATTESTATION_COLUMNS) + ']::text[]'
    await check("(SELECT array_agg(attname::text ORDER BY attnum)=" + columns
        + " FROM pg_attribute WHERE attrelid='cragkit_qdrant.preparation_attestations'::regclass AND attnum>0 AND NOT attisdropped)", 'attestation_exact_columns')
    await check("(SELECT NOT prosecdef AND proconfig=ARRAY['search_path=pg_catalog']::text[] FROM pg_proc WHERE oid='cragkit_qdrant.guard_preparation_attestation()'::regprocedure)", 'attestation_invoker_guard')
    await check("EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='cragkit_qdrant.preparation_attestations'::regclass AND tgname='publication_preparation_attestation_guard' AND tgenabled='O')", 'attestation_enabled_guard')
    key_columns = 'ARRAY[' + ','.join(literal(column) for column in ATTESTATION_KEY) + ']::text[]'
    await check("(SELECT array_agg(a.attname::text ORDER BY k.ord)=" + key_columns
        + " FROM pg_constraint c CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY k(num,ord) JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.num WHERE c.conrelid='cragkit_qdrant.preparation_attestations'::regclass AND c.contype='p')", 'attestation_exact_primary_key')
    await check("(SELECT count(*)=2 FROM pg_constraint WHERE conrelid='cragkit_qdrant.preparation_attestations'::regclass AND contype='f' AND confrelid IN ('cragkit_qdrant.preparations'::regclass,'cragkit_qdrant.backend_instances'::regclass))", 'attestation_original_and_instance_foreign_keys')
    await check("(SELECT count(*)=2 FROM pg_policy WHERE polrelid='cragkit_qdrant.preparation_attestations'::regclass AND polname IN ('writer_attestation_read','writer_attestation_insert') AND polroles=ARRAY['cragkit_qdrant_writer'::regrole::oid])", 'attestation_writer_only_policies')
    checks.append(CHECKS[0])
    if await _snapshot(connection, state) != state.legacy_snapshot:
        raise RuntimeError('attestation_upgrade_changed_legacy_facts')
    checks.append(CHECKS[1])
    # ACL checks use actual nonowner roles; PUBLIC is inspected through aclitem expansion.
    await check("NOT EXISTS(SELECT 1 FROM pg_class c CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a WHERE c.oid='cragkit_qdrant.preparation_attestations'::regclass AND a.grantee=0)", 'attestation_no_public_table_acl')
    await check("NOT EXISTS(SELECT 1 FROM pg_proc p CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE p.oid='cragkit_qdrant.guard_preparation_attestation()'::regprocedure AND a.grantee=0)", 'attestation_no_public_guard_execution')
    for kind in ('writer', 'reader', 'supervisor'):
        await role(kind)
        allowed = kind == 'writer'
        await check("has_table_privilege(current_user,'cragkit_qdrant.preparation_attestations','SELECT')=" + str(allowed).lower(), 'attestation_' + kind + '_select_privilege')
        await check("has_table_privilege(current_user,'cragkit_qdrant.preparation_attestations','INSERT')=" + str(allowed).lower(), 'attestation_' + kind + '_insert_privilege')
        await reject('UPDATE cragkit_qdrant.preparation_attestations SET verification_id=verification_id;', '42501')
        await reject('DELETE FROM cragkit_qdrant.preparation_attestations;', '42501')
        await reject('TRUNCATE cragkit_qdrant.preparation_attestations;', '42501')
        if not allowed:
            await reject('SELECT * FROM cragkit_qdrant.preparation_attestations;', '42501')
            await reject(insert_sql('preparation_attestations', attestation_record(state)), '42501')
    checks.append(CHECKS[2])
    await role('supervisor')
    await command("UPDATE cragkit_qdrant.backend_instances SET epoch=2,state='recovery_blocked',recovery_id='synthetic-sql-recovery-2' WHERE instance_id=" + literal(records['backend']['instance_id']))
    await command('UPDATE cragkit_qdrant.document_owners SET backend_epoch=2 WHERE ' + where)
    await command("UPDATE cragkit_qdrant.backend_instances SET state='open',recovery_id=NULL WHERE instance_id=" + literal(records['backend']['instance_id']))
    await settings()
    await role('writer')
    await command('UPDATE cragkit_qdrant.document_owners SET owner_token=' + literal(OWNER_CURRENT) + ' WHERE ' + where)
    await reject(' '.join(final_cas()))
    checks.append(CHECKS[3])
    for changes in ({'owner_token': OWNER_OLD}, {'backend_epoch': 1}, {'backend_epoch': 3},
        {'instance_id': 'other-instance'}, {'manifest_sha256': 'a' * 64},
        {'authorization_revision': 'other-auth'}, {'mutation_epoch': 2},
        {'expected_active_generation_id': 'other-generation'}):
        await reject(insert_sql('preparation_attestations', attestation_record(state, **changes)))
    await role('admin')
    await case([*fault('preparations', 'UPDATE cragkit_qdrant.preparations SET backend_epoch=2 WHERE ' + intent_where),
        'SET LOCAL ROLE ' + state.roles['writer'], rejected_sql(insert_sql('preparation_attestations', attestation_record(state)), '23514')])
    await role('writer')
    checks.append(CHECKS[4])
    # Each intentionally contradictory state is admin-seeded then rolled back.
    for table, mutation in [
        ('backend_instances', "UPDATE cragkit_qdrant.backend_instances SET state='recovery_blocked',recovery_id='synthetic-fault' WHERE instance_id=" + literal(records['backend']['instance_id'])),
        ('publication_intents', "UPDATE cragkit_qdrant.publication_intents SET state='writing' WHERE " + intent_where),
        ('dispatch_journal', "UPDATE cragkit_qdrant.dispatch_journal SET state='unknown',completion_sha256=NULL WHERE " + where),
        ('documents', 'UPDATE cragkit_qdrant.documents SET tombstoned=true WHERE ' + where),
        ('documents', "UPDATE cragkit_qdrant.documents SET authorization_revision='changed',mutation_epoch=2 WHERE " + where),
        ('documents', 'UPDATE cragkit_qdrant.documents SET active_generation_id=' + literal(records['generation']['generation_id']) + ' WHERE ' + where),
    ]:
        await role('admin')
        await case([*fault(table, mutation), 'SET LOCAL ROLE ' + state.roles['writer'],
            rejected_sql(insert_sql('preparation_attestations', attestation_record(state)), '23514')])
    # A distinct same-document intent proves the guard checks the whole journal,
    # rather than only dispatches belonging to the prepared intent.
    other_intent = dict(records['intent'], intent_id='synthetic-sql-other-intent')
    request = b'{"synthetic_sql_only":"other_intent_uncertainty"}'
    other_dispatch = {key: records['document'][key] for key in ('tenant_id', 'collection', 'document_id')}
    other_dispatch.update(intent_id=other_intent['intent_id'], dispatch_id='synthetic-sql-other-dispatch',
        instance_id=records['backend']['instance_id'], sequence=2, owner_token=OWNER_CURRENT, backend_epoch=2,
        credential_generation='synthetic-sql-credential-2', operation='complete_point_upsert',
        request_bytes=request, request_sha256=sha256(request).hexdigest())
    await role('admin')
    await case([*fault('publication_intents', insert_sql('publication_intents', other_intent)),
        *fault('dispatch_journal', insert_sql('dispatch_journal', other_dispatch)),
        'SET LOCAL ROLE ' + state.roles['writer'], rejected_sql(insert_sql('preparation_attestations', attestation_record(state)), '23514')])
    checks.append(CHECKS[5])
    for table in ('members', 'point_claims', 'vector_replays'):
        await role('admin')
        dependencies = []
        if table == 'point_claims':
            dependencies = [*fault('vector_replays', 'DELETE FROM cragkit_qdrant.vector_replays WHERE ' + where
                + ' AND chunk_id=' + literal(records['members'][0]['chunk_id'])),
                *fault('dispatch_points', 'DELETE FROM cragkit_qdrant.dispatch_points WHERE ' + where
                + ' AND point_id=' + literal(records['members'][0]['point_id']))]
        await case([*dependencies, *fault(table, 'DELETE FROM cragkit_qdrant.' + table + ' WHERE ' + where
            + ' AND chunk_id=' + literal(records['members'][0]['chunk_id'])),
            'SET LOCAL ROLE ' + state.roles['writer'], rejected_sql(insert_sql('preparation_attestations', attestation_record(state)), '23514')])
    await role('admin')
    await case([*fault('point_claims', "UPDATE cragkit_qdrant.point_claims SET text_sha256=repeat('a',64) WHERE "
        + where + ' AND chunk_id=' + literal(records['members'][0]['chunk_id'])),
        'SET LOCAL ROLE ' + state.roles['writer'], rejected_sql(insert_sql('preparation_attestations', attestation_record(state)), '23514')])
    checks.append(CHECKS[6])
    await role('writer')
    await command(insert_sql('preparation_attestations', attestation_record(state)))
    for changes in ({'tenant_id': 'foreign'}, {'writer_intent_id': 'foreign'}, {'backend_instance_id': 'foreign'}):
        await settings(**changes)
        await check('(SELECT count(*)=0 FROM cragkit_qdrant.preparation_attestations)', 'attestation_wrong_scope_hidden')
        await reject(insert_sql('preparation_attestations', attestation_record(state)), '23514')
    await settings()
    checks.append(CHECKS[7])
    await reject(insert_sql('preparation_attestations', attestation_record(state)), '23505')
    checks.append(CHECKS[8])
    await role('admin')
    await reject('UPDATE cragkit_qdrant.preparation_attestations SET readback_sha256=readback_sha256 WHERE ' + intent_where)
    await reject('DELETE FROM cragkit_qdrant.preparation_attestations WHERE ' + intent_where)
    checks.append(CHECKS[9])
    # Additional tuples are explicitly invalid admin fault fixtures, not attestations issued by F1.
    other_rows = [attestation_record(state, owner_token=OWNER_OLD, readback_sha256='b' * 64),
                  attestation_record(state, backend_epoch=99, readback_sha256='c' * 64)]
    await case([*fault('preparation_attestations', ' '.join(insert_sql('preparation_attestations', row) for row in other_rows)),
        'SET LOCAL ROLE ' + state.roles['writer'], *final_cas(),
        assert_sql("(SELECT state='published' FROM cragkit_qdrant.publication_intents WHERE " + intent_where + ')', 'attestation_exact_tuple_with_decoys')])
    checks.append(CHECKS[10])
    await role('admin')
    await case([*fault('preparation_attestations', 'DELETE FROM cragkit_qdrant.preparation_attestations WHERE ' + intent_where
        + ' AND backend_epoch=2 AND owner_token=' + literal(OWNER_CURRENT) + '; '
        + ' '.join(insert_sql('preparation_attestations', row) for row in other_rows)),
        'SET LOCAL ROLE ' + state.roles['writer'], rejected_sql(' '.join(final_cas()), '23514')])
    checks.append(CHECKS[11])
    await role('writer')
    await case([*final_cas(), assert_sql("(SELECT state='published' AND generation_id="
        + literal(records['generation']['generation_id']) + ' FROM cragkit_qdrant.publication_intents WHERE ' + intent_where + ')', 'attestation_same_intent_generation_published')])
    checks.append(CHECKS[12])
    await role('admin')
    if (await _snapshot(connection, state))[0][2] != state.legacy_snapshot[0][2]:
        raise RuntimeError('attestation_original_preparation_changed')
    await command('SET CONSTRAINTS ALL IMMEDIATE')
    checks.append(CHECKS[13])
    return checks
