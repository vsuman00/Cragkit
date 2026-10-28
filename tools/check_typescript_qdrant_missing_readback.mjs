/** Actual missing-only readback observations; no SQL, receipt or settlement proof. */
import {execFile} from 'node:child_process';
import {isDeepStrictEqual as same} from 'node:util';
import {ManagedQdrantSupervisor} from '../packages/typescript/dist/qdrant-supervisor.js';
import {now, bounded} from '../packages/typescript/dist/postgres-pool.js';
import {IntegrityViolation, ProviderUnavailable, UnsupportedCapability} from '../packages/typescript/dist/errors.js';

const CHECKS = Object.freeze([
  'missing_expected_ids_reported',
  'wrong_vectors_and_foreign_payload_rejected',
  'unexpected_scoped_member_rejected',
  'get_scroll_membership_drift_rejected',
  'complete_readback_shares_actual_byte_budget',
]);
const ERROR_NAMES = new Set(['IntegrityViolation','UnauthorizedScope','IndexNotReady','InvalidRequest',
  'ProviderUnavailable','UnsupportedCapability','DeadlineExceeded','AbortError']);
import {QdrantPayloadSchema} from '../packages/typescript/dist/qdrant-contract.js';
import {encode_dense, encode_sparse} from '../packages/typescript/dist/qdrant-vectors.js';
import {inspect_missing_readback, verify_projection_readback, VerificationBudget} from '../packages/typescript/dist/qdrant-reconciliation.js';

const cancellation = new AbortController();
let readingInput = true, step = 0;
const cancel = () => { cancellation.abort(); if (readingInput) process.stdin.destroy(); };
process.on('SIGTERM', cancel); process.on('SIGINT', cancel);
const bytes = value => [...Buffer.from(JSON.stringify(value), 'utf8')];
const decode = value => JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(Buffer.from(value)));
function outcome(error) {
  let name;
  try { name = error?.name; } catch { return 'internal'; }
  return ERROR_NAMES.has(name) ? name : 'internal';
}
class RuntimeCleanupFailure extends Error {
  constructor(primary, failures) {
    super('runtime_cleanup_failed'); this.primary = primary ? outcome(primary) : null; this.failures = failures;
  }
}
async function input() {
  const chunks = []; let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > 262144) throw new Error('bounded_input');
    chunks.push(chunk);
  }
  const value = JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks)));
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || !same(Object.keys(value).sort(), ['binary','inputs','work_dir'])
    || typeof value.binary !== 'string' || typeof value.work_dir !== 'string'
    || !value.inputs || typeof value.inputs !== 'object' || Array.isArray(value.inputs)
    || !Array.isArray(value.inputs.points) || value.inputs.points.length !== 2) {
    throw new Error('input_shape');
  }
  return value;
}
async function denied(operation, classes) {
  try { await operation(); }
  catch (error) { if (classes.some(Type => error instanceof Type)) return; throw error; }
  throw new Error('expected_refusal_missing');
}
function completed(raw) {
  const value = decode(raw);
  if (value?.status !== 'ok' || value?.result?.status !== 'completed') throw new Error('write_not_completed');
}
async function observedListener(address, absent = false) {
  const parsed = new URL(address);
  if (parsed.protocol !== 'http:' || parsed.hostname !== '127.0.0.1' || !parsed.port
    || parsed.username || parsed.password || parsed.origin !== address) throw new Error('endpoint_shape');
  return new Promise((resolve,reject) => execFile('/usr/sbin/lsof',
    ['-nP','-a','-iTCP@127.0.0.1:'+parsed.port,'-sTCP:LISTEN','-t'],
    {encoding:'utf8',env:{PATH:'/usr/bin:/bin'},maxBuffer:1024,timeout:3000,killSignal:'SIGKILL'},
    (error,stdout,stderr) => {
      if (absent && error?.code === 1 && stdout === '' && stderr === '') return resolve(null);
      if (error || stderr || absent || !/^[1-9][0-9]{0,9}\n?$/.test(stdout)) return reject(new Error('listener_observation'));
      const pid = Number(stdout.trim());
      if (!Number.isSafeInteger(pid) || pid > 2147483647) return reject(new Error('listener_observation'));
      resolve(pid);
    }));
}
async function cases(value) {
  const {inputs} = value;
  const options = {deadline:now()+100,signal:cancellation.signal};
  const supervisor = new ManagedQdrantSupervisor(value.binary,value.work_dir,inputs.instance_id,inputs.config);
  const expected = Object.freeze({tombstoned:false,points:Object.freeze(inputs.points.map(point=>Object.freeze({
    point_id:point.id,payload:QdrantPayloadSchema.parse(point.payload),
    dense:encode_dense(point.vector.dense,inputs.config.dense_profile),
    sparse:encode_sparse(point.vector.sparse.indices,point.vector.sparse.values,inputs.config.sparse_profile),
  })))});
  const checks = [];
  let address, primary;
  const target = '/collections/'+inputs.config.physical_collection;
  const clone = value => JSON.parse(JSON.stringify(value));
  const mark = () => { checks.push(CHECKS[checks.length]); step = checks.length; };
  try {
    await supervisor.initialize({...options,provision:async(admin,probe)=>{
      await admin.request('PUT',target,{...options,body:bytes(inputs.collection_config)});
      await admin.request('PUT','/collections/'+probe.collection,{...options,body:bytes(probe.collection_config)});
      completed(await admin.request('PUT','/collections/'+probe.collection+'/points?wait=true&ordering=strong',
        {...options,body:bytes({points:[probe.point]})}));
    }});
    address = supervisor.identity().endpoint; await observedListener(address);
    supervisor.block_ordinary();
    const proof = await supervisor.recover({recovery_id:'missing-native',old_epoch:1,new_epoch:2},options);
    await supervisor.control_session(async control=>{
      let sequence = 0;
      function handle() {
        const attempt = control.issue_recovery_attempt(proof,{intent_id:'missing-native-intent',
          owner_token:'00000000-0000-4000-8000-000000000001',epoch:2,
          dispatch_id:'missing-native-'+String(++sequence),recovery_id:'missing-native'},options);
        return control.recovery_transport_for(attempt);
      }
      const read = handle(), mutation = handle();
      async function put(points) {
        completed(await mutation.request('PUT',target+'/points?wait=true&ordering=strong',
          {...options,body:bytes({points})}));
      }
      async function remove(ids) {
        completed(await mutation.request('POST',target+'/points/delete?wait=true&ordering=strong',
          {...options,body:bytes({points:ids})}));
      }
      await put([inputs.points[0]]);
      const missing = await inspect_missing_readback(read,inputs.config.physical_collection,expected,options);
      if (!same(missing,[inputs.points[1].id])) throw new Error('missing_ids_mismatch');
      mark();
      const wrongVector = clone(inputs.points[0]);
      wrongVector.vector.dense = wrongVector.vector.dense.map(value=>-value);
      await put([wrongVector]);
      await denied(()=>inspect_missing_readback(read,inputs.config.physical_collection,expected,options),[IntegrityViolation]);
      const foreign = clone(inputs.points[0]); foreign.payload.tenant_id = 'foreign-native-tenant';
      await put([foreign]);
      await denied(()=>inspect_missing_readback(read,inputs.config.physical_collection,expected,options),[IntegrityViolation]);
      await put([inputs.points[0]]); mark();
      const extra = clone(inputs.points[0]); extra.id = 'ffffffff-ffff-5fff-8fff-ffffffffffff';
      await put([extra]);
      await denied(()=>inspect_missing_readback(read,inputs.config.physical_collection,expected,options),[IntegrityViolation]);
      await remove([extra.id,inputs.points[1].id]); mark();
      let changed = false;
      const drifting = {async request(method,path,requestOptions) {
        if (!changed && path.endsWith('/scroll')) {
          changed = true;
          await put([inputs.points[1]]);
        }
        return read.request(method,path,requestOptions);
      },async close(){}};
      await denied(()=>inspect_missing_readback(drifting,inputs.config.physical_collection,expected,options),[IntegrityViolation]);
      if (!changed) throw new Error('drift_not_exercised'); mark();
      await put(inputs.points);
      let observedBytes = 0;
      const measured = {async request(method,path,requestOptions) {
        const raw = await read.request(method,path,requestOptions);
        observedBytes += raw.length;
        return raw;
      },async close(){}};
      const budget = new VerificationBudget();
      for (let pass=0;pass<2;pass++) {
        const absent = await inspect_missing_readback(measured,inputs.config.physical_collection,expected,options,budget);
        if (absent.length || budget.remaining_bytes !== 8388608-observedBytes) throw new Error('shared_inspection_budget_mismatch');
      }
      await verify_projection_readback(measured,inputs.config.physical_collection,expected,options,budget);
      if (observedBytes <= 0 || budget.remaining_bytes !== 8388608-observedBytes) throw new Error('shared_strict_budget_mismatch');
      mark();
    });
    return {runtime:'typescript',checks,proof_scope:'missing_only_inspection_and_budget_only'};
  } catch (error) { primary = error; throw error; }
  finally {
    const failures = [], deadline = now()+12;
    try { await bounded(supervisor.close(),{deadline:Math.min(now()+8,deadline)}); }
    catch (error) { failures.push({operation:'controller_close',outcome:outcome(error)}); }
    if (address) {
      try { await observedListener(address,true); }
      catch (error) { failures.push({operation:'listener_close',outcome:outcome(error)}); }
    }
    if (failures.length) throw new RuntimeCleanupFailure(primary,failures);
  }
}

try {
  const value = await bounded(input(),{deadline:now()+5,signal:cancellation.signal}); readingInput = false;
  process.stdout.write(JSON.stringify(await cases(value))+'\n');
} catch (error) {
  process.stdout.write(JSON.stringify(error instanceof RuntimeCleanupFailure
    ? {ok:false,step,error:'cleanup_failed',primary:error.primary,cleanup:error.failures}
    : {ok:false,step,error:outcome(error)})+'\n'); process.exitCode = 1;
} finally { process.removeListener('SIGTERM',cancel); process.removeListener('SIGINT',cancel); }
