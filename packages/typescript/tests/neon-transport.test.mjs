import test from 'node:test';
import assert from 'node:assert/strict';
import { requireNeonTLS, verifyNeonResource } from '../../../tools/check_typescript_postgres.mjs';

const host = 'ep-synthetic-test-1234.c-4.ap-southeast-1.aws.neon.tech';
function client() {
  return { connection: { stream: { encrypted: true, authorized: true } },
    ssl: { rejectUnauthorized: true, servername: host } };
}

test('Neon native transport requires authorized TLS and the exact server name', () => {
  requireNeonTLS(client(), host);
  for (const value of [false, undefined, 'true', 1]) {
    for (const field of ['encrypted', 'authorized']) {
      const fake = client();
      fake.connection.stream[field] = value;
      assert.throws(() => requireNeonTLS(fake, host), /native_client_tls_required/);
    }
    const fake = client();
    fake.ssl.rejectUnauthorized = value;
    assert.throws(() => requireNeonTLS(fake, host), /native_client_tls_required/);
  }
  const wrong = client();
  wrong.ssl.servername = 'other.invalid';
  assert.throws(() => requireNeonTLS(wrong, host), /native_client_tls_required/);
});

test('Neon fixture transport rejects pooled hosts, suffix lookalikes and absent sockets', () => {
  for (const wrong of [host.replace('.c-4', '-pooler.c-4'), host + '.attacker.invalid',
    'localhost', '127.0.0.1', 'other.neon.tech', undefined]) {
    assert.throws(() => requireNeonTLS(client(), wrong), /direct_neon_host_required/);
  }
  for (const wrong of [null, {}, { connection: {} }]) {
    assert.throws(() => requireNeonTLS(wrong, host), /native_client_tls_required/);
  }
});

test('Neon fixture verifies raw driver TLS before guarded leases and destroys invalid clients', async () => {
  let destroyed = false;
  const valid = { ...client(), release: value => { destroyed = value; } };
  const pool = { connect: async () => valid };
  const config = { host };
  const resource = { factory: async received => {
    assert.equal(received, config);
    return pool;
  } };
  verifyNeonResource(resource, host);
  const wrapped = await resource.factory(config);
  assert.equal(await wrapped.connect(), valid);
  assert.equal(destroyed, false);
  valid.connection.stream.authorized = false;
  await assert.rejects(wrapped.connect(), /native_client_tls_required/);
  assert.equal(destroyed, true);
  assert.throws(() => verifyNeonResource({}, host), /native_factory_unavailable/);
});
