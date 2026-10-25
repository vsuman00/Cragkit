import test from 'node:test';
import assert from 'node:assert/strict';
import {verified_tls_options} from '../dist/postgres-pool.js';

test('verified DNS TLS keeps the configured CA, hostname and certificate verification',()=>{
  const options=verified_tls_options('database.example.invalid','synthetic-ca');
  assert.deepEqual(options,{ca:'synthetic-ca',rejectUnauthorized:true,servername:'database.example.invalid'});
  assert.ok(Object.isFrozen(options));
});

for(const host of ['127.0.0.1','192.0.2.10','::1','2001:db8::1']){
  test(`verified IP TLS omits SNI without relaxing verification (${host})`,()=>{
    const options=verified_tls_options(host,'synthetic-ca');
    assert.deepEqual(options,{ca:'synthetic-ca',rejectUnauthorized:true});
    assert.equal(Object.hasOwn(options,'servername'),false);
    assert.ok(Object.isFrozen(options));
  });
}
