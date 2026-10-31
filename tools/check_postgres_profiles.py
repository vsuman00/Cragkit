"""Explicit, atomic PGO-r1 profile upgrade; library imports never invoke this tool."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path

from check_postgres import LOCK, PostgresCheckError, connection_environment, execute, migrations

ROOT = Path(__file__).resolve().parents[1]
SETUP_IDENTITIES = (
    ('0001_pgvector', 'b98de4a67f46ab7cc7187447757b30844ceee01901a88186746ae322cf1a7e2c'),
    ('0002_vector_profiles', '33fda8141215cbdb961165822a13bc74639c97c41985529ce1b1b3ae585140fb'),
    ('0003_openai_te3small_1536', '9f909b14e690112fbc4c8671f7e758e839e615e68aad33f927b400ea04eb9f16'),
)
CATALOG_SHA256 = '65fbbb3b2a747e20ad8fea5739cbfe2bf95708dafa61e4d9a095d17c9f1322d0'
MARKER = 'cragkit_postgres_profiles_ok'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _json(value: object) -> str:
    return _literal(json.dumps(value, separators=(',', ':'))) + '::jsonb'


def _assert_sql(condition: str, code: str) -> str:
    return (f"IF NOT coalesce(({condition}),false) THEN RAISE EXCEPTION "
            f"USING ERRCODE='CV002', MESSAGE='{code}'; END IF;")


def _history_query(table: str, *, timestamps: bool = False, legacy_only: bool = False) -> str:
    columns = 'version,checksum,applied_at' if timestamps else 'version,checksum'
    where = " WHERE version IN ('0001_pgvector','0002_vector_profiles')" if legacy_only else ''
    return (f"SELECT coalesce(jsonb_agg(jsonb_build_array({columns}) ORDER BY version),'[]'::jsonb) "
            f'FROM {table}{where}')


def _table_guard(table: str, columns: list, constraints: list) -> str:
    """Compare native catalog semantics, independently of truncated key names."""
    relation = _literal('cragkit.' + table)
    expected = sorted([[row[1], row[5], row[2], row[3], row[4]] for row in constraints])
    return f"""
EXISTS(SELECT 1 FROM pg_class c WHERE c.oid=to_regclass({relation})
 AND c.relkind='r' AND c.relrowsecurity AND c.relowner=current_user::regrole)
AND (SELECT jsonb_agg(jsonb_build_array(a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull)
 ORDER BY a.attnum) FROM pg_attribute a WHERE a.attrelid=to_regclass({relation})
 AND a.attnum>0 AND NOT a.attisdropped)={_json(columns)}
AND (SELECT jsonb_agg(jsonb_build_array(c.contype::text,pg_get_constraintdef(c.oid,true),
 c.convalidated,c.condeferrable,c.condeferred) ORDER BY c.contype::text,pg_get_constraintdef(c.oid,true))
 FROM pg_constraint c WHERE c.conrelid=to_regclass({relation}))={_json(expected)}
AND NOT EXISTS(SELECT 1 FROM pg_class c,
 LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
 WHERE c.oid=to_regclass({relation}) AND a.grantee=0)
AND NOT EXISTS(SELECT 1 FROM pg_trigger t WHERE t.tgrelid=to_regclass({relation})
 AND t.tgenabled NOT IN ('O','A'))
AND NOT EXISTS(SELECT 1 FROM pg_constraint c WHERE c.conrelid=to_regclass({relation})
 AND c.contype='f' AND ((SELECT count(*) FROM pg_trigger t
 WHERE t.tgconstraint=c.oid AND t.tgisinternal)<>4
 OR EXISTS(SELECT 1 FROM pg_trigger t WHERE t.tgconstraint=c.oid
 AND (NOT t.tgisinternal OR t.tgenabled NOT IN ('O','A')))))
"""


def _registry_guard(catalog: dict, *, upgraded: bool) -> str:
    rows = catalog['registry'] if upgraded else catalog['registry'][:1]
    definition = catalog['registry_checks'][0][1]
    if not upgraded:
        definition = definition.split(' OR profile_id::text = ', 1)[0] + ')'
    return f"""
(SELECT jsonb_agg(jsonb_build_array(profile_id,provider,model,dimensions,tokenizer,normalization,
 storage_table) ORDER BY profile_id) FROM cragkit.embedding_profiles)={_json(rows)}
AND (SELECT count(*) FROM pg_constraint c WHERE c.conrelid='cragkit.embedding_profiles'::regclass
 AND c.contype='c')=1
AND EXISTS(SELECT 1 FROM pg_constraint c WHERE c.conrelid='cragkit.embedding_profiles'::regclass
 AND c.contype='c' AND c.convalidated AND NOT c.condeferrable AND NOT c.condeferred
 AND pg_get_constraintdef(c.oid,true)={_literal(definition)})
AND EXISTS(SELECT 1 FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid
 WHERE t.tgrelid='cragkit.embedding_profiles'::regclass AND t.tgname='immutable_embedding_profile'
 AND NOT t.tgisinternal AND t.tgenabled IN ('O','A') AND t.tgtype=27
 AND p.oid=to_regprocedure('cragkit.reject_embedding_profile_change()') AND NOT p.prosecdef)
"""


def profile_upgrade_script(*, apply: bool, root: Path = ROOT) -> str:
    """Render only pinned artifacts. Unknown histories/catalogs are never repaired."""
    setup = migrations(root / 'storage/postgres/setup')
    if tuple((item.version, item.checksum) for item in setup) != SETUP_IDENTITIES:
        raise PostgresCheckError('profile_setup_artifact_drift')
    data = (root / 'contracts/fixtures/postgres_openai_catalog_v6.json').read_bytes()
    if sha256(data).hexdigest() != CATALOG_SHA256:
        raise PostgresCheckError('profile_catalog_artifact_drift')
    catalog = json.loads(data)
    lexical = [(item.version, item.checksum) for item in migrations(root / 'storage/postgres/migrations')]
    history = _history_query('cragkit_vector.setup_history')
    lexical_before = _history_query('cragkit.migration_history', timestamps=True)
    setup_before = _history_query('cragkit_vector.setup_history', timestamps=True, legacy_only=True)
    statements = ["""BEGIN;
SET LOCAL search_path = pg_catalog;
SET LOCAL statement_timeout = '30s';
SET LOCAL lock_timeout = '5s';
SET LOCAL idle_in_transaction_session_timeout = '30s';"""]
    if not apply:
        statements.append('SET TRANSACTION READ ONLY;')
    statements.extend([f'SELECT {LOCK};', """DO $cragkit_profile$
DECLARE lexical_before jsonb; setup_before jsonb; legacy boolean;
BEGIN
IF to_regclass('cragkit.migration_history') IS NULL
 OR to_regclass('cragkit_vector.setup_history') IS NULL
 OR to_regclass('cragkit.embedding_profiles') IS NULL THEN
 RAISE EXCEPTION USING ERRCODE='CV001', MESSAGE='profile_prerequisite_missing';
END IF;"""])
    statements.append(_assert_sql(f"({history}) IN ({_json(SETUP_IDENTITIES[:2])},{_json(SETUP_IDENTITIES)})",
                                  'profile_setup_history_drift'))
    statements.append(_assert_sql(f"({_history_query('cragkit.migration_history')})={_json(lexical)}",
                                  'profile_lexical_history_drift'))
    statements.append("""IF NOT EXISTS(SELECT 1 FROM pg_extension e
 JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'
 AND e.extversion='0.8.0' AND n.nspname='cragkit_vector')
 OR NOT EXISTS(SELECT 1 FROM pg_type t JOIN pg_depend d ON d.objid=t.oid
 JOIN pg_extension e ON e.oid=d.refobjid WHERE t.oid=to_regtype('cragkit_vector.vector')
 AND t.typtype='b' AND d.classid='pg_type'::regclass AND d.refclassid='pg_extension'::regclass
 AND d.deptype='e' AND e.extname='vector')
 OR EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname IN ('cragkit','cragkit_vector') AND p.prosecdef) THEN
 RAISE EXCEPTION USING ERRCODE='CV002', MESSAGE='profile_extension_incompatible'; END IF;
IF EXISTS(SELECT 1 FROM (VALUES ('cragkit.migration_history'),('cragkit_vector.setup_history'),
 ('cragkit.embedding_profiles')) expected(name) LEFT JOIN pg_class c ON c.oid=to_regclass(expected.name)
 WHERE c.relkind IS DISTINCT FROM 'r' OR c.relowner IS DISTINCT FROM current_user::regrole
 OR NOT coalesce(c.relrowsecurity,false))
 OR EXISTS(SELECT 1 FROM pg_class c,
 LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
 WHERE c.oid IN ('cragkit.embedding_profiles'::regclass,'cragkit_vector.setup_history'::regclass,
 'cragkit.migration_history'::regclass) AND a.grantee=0) THEN
 RAISE EXCEPTION USING ERRCODE='CV002', MESSAGE='profile_owner_or_access_incompatible'; END IF;""")
    statements.append(_assert_sql(_table_guard('chunk_vectors_fake_1536', catalog['fake_columns'],
                                              catalog['fake_constraints']), 'profile_fake_catalog_drift'))
    statements.extend([f'lexical_before := ({lexical_before});', f'setup_before := ({setup_before});',
                       f'legacy := ({history})={_json(SETUP_IDENTITIES[:2])};', 'IF legacy THEN'])
    statements.append(_assert_sql(_registry_guard(catalog, upgraded=False), 'profile_legacy_registry_drift'))
    statements.append(_assert_sql("to_regclass('cragkit.chunk_vectors_openai_te3small_1536') IS NULL",
                                  'profile_unmanaged_table'))
    if apply:
        item = setup[2]
        statements.extend([item.sql, f"INSERT INTO cragkit_vector.setup_history(version,checksum) "
                           f"VALUES ('{item.version}','{item.checksum}');"])
    else:
        statements.append("RAISE EXCEPTION USING ERRCODE='CV002', MESSAGE='profile_upgrade_pending';")
    statements.extend(['END IF;', _assert_sql(f'({history})={_json(SETUP_IDENTITIES)}', 'profile_upgrade_history_drift'),
                       _assert_sql(_registry_guard(catalog, upgraded=True), 'profile_registry_drift'),
                       _assert_sql(_table_guard('chunk_vectors_openai_te3small_1536', catalog['columns'],
                                               catalog['constraints']), 'profile_openai_catalog_drift'),
                       _assert_sql(f'lexical_before=({lexical_before}) AND setup_before=({setup_before})',
                                   'profile_prior_history_changed'),
                       'END $cragkit_profile$;', 'COMMIT;', f"SELECT '{MARKER}';"])
    return '\n'.join(statements)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--check', action='store_true')
    parser.add_argument('--confirm-dedicated-target', action='store_true', required=True)
    parser.add_argument('--local-socket', type=Path)
    parser.add_argument('--psql', default='psql')
    args = parser.parse_args()
    try:
        script = profile_upgrade_script(apply=args.apply)
        environment = connection_environment(os.environ, confirmed=args.confirm_dedicated_target,
                                             local_socket=args.local_socket)
        execute(script, environment, executable=args.psql, marker=MARKER)
    except (OSError, ValueError, PostgresCheckError):
        print(json.dumps({'state': 'failed', 'code': 'postgres_profile_check_failed'}))
        return 1
    print(json.dumps({'state': 'verified', 'profile': 'openai_te3small_1536_r1',
                      'mode': 'apply' if args.apply else 'check'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
