/** Actual session-owned recovery HTTP observations; no SQL or publication proof. */
import {execFile} from 'node:child_process';
import {isDeepStrictEqual as same} from 'node:util';
import {ManagedQdrantSupervisor} from '../packages/typescript/dist/qdrant-supervisor.js';
import {now, bounded} from '../packages/typescript/dist/postgres-pool.js';
import {InvalidRequest, ProviderUnavailable, UnsupportedCapability} from '../packages/typescript/dist/errors.js';

const CHECKS = Object.freeze([
  'real_recovery_session_writes_and_reads',
  'raw_and_foreign_attempts_cannot_join_session',
  'eight_live_handles_close_reuses_slot',
  'expired_facade_and_handles_reject_requests',
  'borrowed_handle_survives_owned_cleanup',
]);
const ERROR_NAMES = new Set(['IntegrityViolation','UnauthorizedScope','IndexNotReady','InvalidRequest',
  'ProviderUnavailable','UnsupportedCapability','DeadlineExceeded','AbortError']);
const cancellation = new AbortController();
let readingInput = true, step = 0;
const cancel = () => { cancellation.abort(); if (readingInput) process.stdin.destroy(); };
process.on('SIGTERM', cancel); process.on('SIGINT', cancel);
const bytes = value => [...Buffer.from(JSON.stringify(value), 'utf8')];
const decode = value => JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(Buffer.from(value)));
const byId = (left,right) => left.id < right.id ? -1 : left.id > right.id ? 1 : 0;
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
    || !Array.isArray(value.inputs.points) || value.inputs.points.length < 1 || value.inputs.points.length > 8) {
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
  const checks = [];
  let address, borrowed, expired, captured, primary;
  const target = '/collections/'+inputs.config.physical_collection;
  const binding = dispatch => ({intent_id:'session-native-intent',
    owner_token:'00000000-0000-4000-8000-000000000001',epoch:2,
    dispatch_id:dispatch,recovery_id:'session-native'});
  const readOptions = () => ({...options,body:bytes({ids:inputs.points.map(point=>point.id),with_payload:true,with_vector:true})});
  async function readback(handle) {
    const raw = decode(await handle.request('POST',target+'/points',readOptions()));
    if (raw?.status !== 'ok' || !Array.isArray(raw.result)) throw new Error('readback_shape');
    const observed = raw.result.map(point=>({id:point.id,payload:point.payload,vector:point.vector})).sort(byId);
    if (!same(observed,[...inputs.points].sort(byId))) throw new Error('complete_readback_mismatch');
  }
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
    const proof = await supervisor.recover({recovery_id:'session-native',old_epoch:1,new_epoch:2},options);
    const rawAttempt = supervisor.issue_recovery_attempt(proof,binding('session-native-borrowed'),options);
    borrowed = supervisor.transport_for(rawAttempt);
    await supervisor.control_session(async control=>{
      expired = control;
      const attempt = control.issue_recovery_attempt(proof,binding('session-native-dispatch'),options);
      const first = control.recovery_transport_for(attempt);
      completed(await first.request('PUT',target+'/points?wait=true&ordering=strong',
        {...options,body:bytes({points:inputs.points})}));
      await readback(first); mark();
      await denied(()=>control.issue_recovery_attempt(JSON.parse(JSON.stringify(proof)),binding('copied-proof'),options),
        [UnsupportedCapability]);
      await denied(()=>supervisor.issue_recovery_attempt(proof,binding('raw-held'),options),[ProviderUnavailable]);
      await denied(()=>supervisor.transport_for(rawAttempt),[ProviderUnavailable]);
      await denied(()=>control.recovery_transport_for(rawAttempt),[InvalidRequest]);
      await denied(()=>control.recovery_transport_for(JSON.parse(JSON.stringify(attempt))),[InvalidRequest]);
      mark();
      const live = [first];
      for (let index=1;index<8;index++) {
        const next = control.issue_recovery_attempt(proof,binding('session-native-slot-'+index),options);
        live.push(control.recovery_transport_for(next));
      }
      const ninth = control.issue_recovery_attempt(proof,binding('session-native-overflow'),options);
      await denied(()=>control.recovery_transport_for(ninth),[ProviderUnavailable]);
      await first.close();
      const replacement = control.recovery_transport_for(ninth);
      await readback(replacement);
      captured = live[1];
      mark();
    });
    const refusal = [ProviderUnavailable,InvalidRequest,UnsupportedCapability];
    await denied(()=>expired.issue_recovery_attempt(proof,binding('expired'),options),refusal);
    await denied(()=>expired.recovery_transport_for(rawAttempt),refusal);
    await denied(()=>captured.request('POST',target+'/points',readOptions()),refusal);
    mark();
    await readback(borrowed); mark();
    return {runtime:'typescript',checks,proof_scope:'recovery_session_transport_only'};
  } catch (error) { primary = error; throw error; }
  finally {
    const failures = [], deadline = now()+12;
    for (const [operation,owner] of [...(borrowed?[['transport_close',borrowed]]:[]),['controller_close',supervisor]]) {
      try { await bounded(Promise.resolve().then(()=>owner.close()),{deadline:Math.max(now()+.001,Math.min(now()+8,deadline))}); }
      catch (error) { failures.push({operation,outcome:outcome(error)}); }
    }
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
