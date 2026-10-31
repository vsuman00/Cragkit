import assert from 'node:assert/strict';
import test from 'node:test';
import { registerHooks, syncBuiltinESMExports } from 'node:module';
import fs from 'node:fs';
import fsPromises from 'node:fs/promises';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import dns from 'node:dns';
import dgram from 'node:dgram';
import childProcess from 'node:child_process';

test('core import exposes version without dependencies or external I/O', async () => {
  const restorations = [];
  const block = (object, names) => {
    for (const name of names) {
      const original = object[name];
      object[name] = () => {
        throw new Error(`Forbidden import side effect: ${name}`);
      };
      restorations.push(() => { object[name] = original; });
    }
  };
  const entry = new URL('../dist/index.js', import.meta.url).href;
  const hooks = registerHooks({
    resolve(specifier, context, nextResolve) {
      const resolved = nextResolve(specifier, context);
      assert.equal(resolved.url, entry, `Unexpected core dependency: ${specifier}`);
      return resolved;
    },
  });
  try {
    block(globalThis, ['fetch', 'WebSocket']);
    block(http, ['request', 'get', 'createServer']);
    block(https, ['request', 'get', 'createServer']);
    block(net, ['connect', 'createConnection', 'createServer']);
    block(tls, ['connect', 'createServer']);
    block(dns, ['lookup', 'resolve']);
    block(dgram, ['createSocket']);
    block(childProcess, ['spawn', 'spawnSync', 'exec', 'execSync', 'execFile', 'execFileSync', 'fork']);
    block(fs, [
      'writeFile', 'writeFileSync', 'appendFile', 'appendFileSync',
      'mkdir', 'mkdirSync', 'rm', 'rmSync', 'unlink', 'unlinkSync',
      'rename', 'renameSync', 'createWriteStream',
    ]);
    block(fsPromises, ['writeFile', 'appendFile', 'mkdir', 'rm', 'unlink', 'rename']);
    syncBuiltinESMExports();
    const core = await import('cragkit');
    assert.deepEqual(Object.keys(core), ['version']);
    assert.equal(core.version, '1.0.0-rc.1');
  } finally {
    hooks.deregister();
    for (const restore of restorations.reverse()) restore();
    syncBuiltinESMExports();
  }
});


test('engine defaults to RC while explicit historical identity remains valid', async () => {
  const { VersionsSchema } = await import('cragkit/contracts');
  const { version } = await import('cragkit');
  assert.equal(VersionsSchema.parse({}).engine, version);
  assert.equal(VersionsSchema.parse({ engine: '0.0.0' }).engine, '0.0.0');
});
