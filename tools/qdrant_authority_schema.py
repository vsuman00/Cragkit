"""Pure, explicit V5 source-schema probe construction; never connects or applies."""
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / 'storage/qdrant/postgres/migrations/0001_authority.sql'


@dataclass(frozen=True)
class AuthorityMigration:
    version: str
    checksum: str
    sql: str


def migration(path=MIGRATION):
    """Read the one source-only migration; production application is separate."""
    if path.name != '0001_authority.sql':
        raise ValueError('authority_migration_identity')
    raw = path.read_bytes()
    sql = raw.decode('utf-8')
    if '\r' in sql or re.search(r'(?mi)^\s*(?:COMMIT|ROLLBACK|BEGIN\s*;|\\)', sql):
        raise ValueError('authority_transaction_boundary')
    if '$qdauth_probe$' in sql:
        raise ValueError('authority_probe_delimiter')
    return AuthorityMigration(path.stem, sha256(raw).hexdigest(), sql)


def literal(value):
    """Quote synthetic fixture values, never connection settings or identifiers."""
    if value is None:
        return 'NULL'
    if type(value) is bool:
        return 'true' if value else 'false'
    if type(value) is int:
        return str(value)
    if type(value) is bytes:
        return "decode('" + value.hex() + "','hex')"
    if type(value) is not str or '\0' in value:
        raise ValueError('authority_fixture_literal')
    return "E'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def fixture_row(path=ROOT / 'contracts/fixtures/qdrant_sources.json'):
    fixture = json.loads(path.read_text())
    def expand(value):
        if type(value) is str and value.startswith('$ref:'):
            target = fixture
            for part in value[5:].split('.'):
                target = target[part]
            return expand(target)
        if type(value) is dict:
            if set(value) == {'encoding', 'value'}:
                if value['encoding'] == 'utf8':
                    return value['value'].encode('utf-8')
                if value['encoding'] == 'hex':
                    return bytes.fromhex(value['value'])
                raise ValueError('authority_fixture_encoding')
            return {key: expand(child) for key, child in value.items()}
        if type(value) is list:
            return [expand(child) for child in value]
        return value
    return expand(fixture['base_row'])


def seed_statements(row):
    """Administrative setup only: the caller owns its rollback transaction."""
    common = ['tenant_id', 'collection', 'document_id']
    def insert(table, columns, values):
        return f"INSERT INTO cragkit_qdrant.{table} ({','.join(columns)}) VALUES ({','.join(values)});"
    def values(columns):
        return [literal(row[key]) for key in columns]
    docs = common + ['authorization_revision', 'mutation_epoch', 'language', 'kind', 'tag']
    acl = ["ARRAY[" + ','.join(literal(item) for item in row[key]) + ']::text[]' for key in ('principal_ids', 'grant_ids')]
    revision = common + ['revision_id', 'canonical_utf8', 'source_sha256', 'source_locator', 'parser_id']
    generation = common + ['revision_id', 'generation_id', 'backend_namespace', 'physical_collection',
                           'collection_incarnation', 'chunker_profile', 'dense_profile_id', 'sparse_profile_id']
    profiles = [literal(json.dumps(row['dense_profile'], separators=(',', ':'))) + '::jsonb',
                'NULL' if row['sparse_profile'] is None else literal(json.dumps(row['sparse_profile'], separators=(',', ':'))) + '::jsonb']
    members = common + ['revision_id', 'generation_id', 'chunk_id', 'point_id', 'start_byte', 'end_byte',
                        'source_sha256', 'text_sha256', 'excerpt_utf8']
    where = ' AND '.join(f'{key}={literal(row[key])}' for key in common)
    return [
        insert('documents', docs + ['principal_ids', 'grant_ids'], values(docs) + acl),
        insert('document_revisions', revision, values(revision)),
        insert('generations', generation + ['dense_profile', 'sparse_profile', 'expected_member_count'], values(generation) + profiles + ['1']),
        insert('members', members, values(members)),
        f"UPDATE cragkit_qdrant.generations SET published=true,ever_published=true WHERE {where} AND generation_id={literal(row['generation_id'])};",
        f"UPDATE cragkit_qdrant.documents SET active_generation_id={literal(row['generation_id'])} WHERE {where};",
    ]


def seed_sql(row):
    return '\n'.join(seed_statements(row))


def assert_sql(condition, label):
    if not re.fullmatch(r'[a-z0-9_]{1,80}', label):
        raise ValueError('authority_assert_label')
    return f"DO $qdauth_probe$ BEGIN IF ({condition}) IS DISTINCT FROM true THEN RAISE EXCEPTION '{label}'; END IF; END $qdauth_probe$;"


def force_rls_sql():
    """Resolve fixture FK events before ALTER TABLE; SQLSTATE 55006 otherwise."""
    tables = ('documents', 'document_revisions', 'generations', 'members')
    return '\n'.join(['SET CONSTRAINTS ALL IMMEDIATE;'] +
                     [f'ALTER TABLE cragkit_qdrant.{table} FORCE ROW LEVEL SECURITY;' for table in tables])
