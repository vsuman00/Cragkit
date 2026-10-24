import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { _ROLE_SQL, PostgresSession } from '../dist/postgres-session.js';
import { _WRITER_ROLE_SQL, PostgresIndexer } from '../dist/ingestion.js';
import { now } from '../dist/postgres-pool.js';
import { UnauthorizedScope } from '../dist/errors.js';

const denied = ['pg_read_all_data', 'pg_write_all_data', 'pg_read_server_files',
  'pg_write_server_files', 'pg_execute_server_program'].sort();

for (const [name, sql, filename] of [['_ROLE_SQL', _ROLE_SQL, '_postgres_session.py'],
  ['_WRITER_ROLE_SQL', _WRITER_ROLE_SQL, 'ingestion.py']]) {
  test(`${name} preserves native parity and denies exact predefined MEMBER roles`, () => {
    const source = readFileSync(new URL(`../../python/src/cragkit/${filename}`, import.meta.url), 'utf8');
    const native = source.match(new RegExp(`${name} = """([\\s\\S]*?)"""`));
    assert.ok(native);
    assert.equal(sql, native[1]);
    assert.ok(sql.includes("pg_has_role(current_user,r.oid,'MEMBER')"));
    assert.ok(!sql.includes("pg_has_role(current_user,r.oid,'USAGE')"));
    const list = sql.match(/r\.rolname IN \(([^)]+)\)/);
    assert.ok(list);
    assert.deepEqual([...list[1].matchAll(/'([^']+)'/g)].map(match => match[1]).sort(), denied);
    for (const attribute of ['rolsuper', 'rolbypassrls', 'rolcreaterole', 'rolcreatedb', 'rolreplication']) {
      assert.ok(sql.includes(`r.${attribute}`));
    }
  });
}

for (const writer of [false, true]) {
  test(`${writer ? 'writer' : 'reader'} denies a negative role decision before catalog/scope/data`, async () => {
    const calls = [];
    const guard = writer ? _WRITER_ROLE_SQL : _ROLE_SQL;
    const client = {
      status: 'I',
      getTransactionStatus() { return this.status; },
      release() { assert.fail('clean rollback must retain client'); },
      async query({ text }) {
        calls.push(text);
        if (text.startsWith('BEGIN')) this.status = 'T';
        if (text === 'ROLLBACK') this.status = 'I';
        if (text === guard) return { rows: [[false]] };
        if (text.startsWith('SELECT') && !text.includes('statement_timeout')) assert.fail('query after denied role');
        return { rows: [] };
      },
    };
    const options = { deadline: now() + 1 };
    if (writer) {
      const indexer = new PostgresIndexer({}, async () => true);
      await assert.rejects(indexer.stage(client, null, null, null, '', '', null, options), UnauthorizedScope);
    } else {
      const resource = { config: { release_timeout: 0.1 },
        withLease: async (input, body) => body(client, new AbortController().signal) };
      await assert.rejects(new PostgresSession(resource).validate(options), UnauthorizedScope);
      assert.equal(client.status, 'I');
    }
    assert.equal(calls.filter(sql => sql === guard).length, 1);
  });
}
