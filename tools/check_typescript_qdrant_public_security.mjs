/** Native public security convergence acceptance. Private configuration arrives on stdin. */
import http from 'node:http';
import {execFile} from 'node:child_process';
import {createHash} from 'node:crypto';
import {isDeepStrictEqual as same} from 'node:util';
import {PoolResource, parse_pool_config, bounded, now} from '../packages/typescript/dist/postgres-pool.js';
import {ExecutionLedger} from '../packages/typescript/dist/execution.js';
import {parse_request} from '../packages/typescript/dist/requests.js';
import {QdrantPublicationManager, PostgresQdrantPublicationAuthority, ManagedQdrantPublicationTransport, PostgresQdrantWriter, PostgresQdrantRecovery, ManagedQdrantSupervisor, QdrantReconciliationVerifier} from '../packages/typescript/dist/qdrant-publication.js';
import {QdrantSecurityManager} from '../packages/typescript/dist/qdrant-security.js';
import {PostgresQdrantSourceStore} from '../packages/typescript/dist/qdrant-source.js';
import {security_projection_data} from '../packages/typescript/dist/qdrant-writer.js';
import {ProviderUnavailable, UnauthorizedScope} from '../packages/typescript/dist/errors.js';
const CHECKS = [
  'public_authority_then_full_document_convergence',
  'completed_retry_has_no_physical_or_authority_mutation',
  'repeated_update_preserves_original_stage_history',
  'acl_replica_ack_lost_replays_current_revocation',
  'revocation_between_stages_denies_stale_publication',
  'lost_completed_ack_keeps_pending_and_retry_refences',
  'current_source_allowed_and_revoked_scopes',
  'ownerless_denied_stage_public_bootstrap',
  'authority_change_during_convergence_refuses_stale_completion',
  'tombstone_during_convergence_denies_source_and_preserves_pending'
];
const ERRORS = new Set([
  'InvalidRequest',
  'IntegrityViolation',
  'ProviderUnavailable',
  'UnauthorizedScope',
  'UnsupportedCapability',
  'DeadlineExceeded',
  'IndexNotReady',
  'BudgetExhausted',
  'AbortError'
]);
const OWNER = '00000000-0000-4000-8000-000000000001';
const controller = new AbortController();
let reading = true, step = 0;
const cancel = () => {
  controller.abort();
  if (reading)process.stdin.destroy();
};
process.on('SIGTERM', cancel);
process.on('SIGINT', cancel);
const assert = value => {
  if (!value) throw new Error('acceptance_failed');
};
const bytes = value => [...Buffer.from(JSON.stringify(value),'utf8')];
const hash = value => createHash('sha256').update(value).digest('hex');
const decode = value => JSON.parse(new TextDecoder('utf-8', {
  fatal: true
}).decode(Buffer.from(value)));
async function input() {
  let size = 0;
  const chunks = [];
  for await(const chunk of process.stdin) {
    size += chunk.length;
    assert(size <= 1048576);
    chunks.push(chunk);
  }
  const value = decode(Buffer.concat(chunks));
  assert(value
    && same(Object.keys(value).sort(), ['binary','inputs','reader_config','supervisor_config','work_dir','writer_config'])
    && typeof value.binary === 'string'
    && typeof value.work_dir === 'string');
  return value;
}
async function listener(address, absent = false) {
  const url = new URL(address);
  assert(url.protocol === 'http:' && url.hostname === '127.0.0.1' && url.port && url.origin === address);
  return new Promise((resolve, reject) => execFile('/usr/sbin/lsof', ['-nP','-a','-iTCP@127.0.0.1:'+url.port,'-sTCP:LISTEN','-t'], {
    encoding:'utf8', env: {
      PATH:'/usr/bin:/bin'
    }, maxBuffer: 1024, timeout: 3000, killSignal:'SIGKILL'
  }, (error, out, err) => {
    if (absent && error?.code === 1 && out === '' && err === '') return resolve();
    if (error || err || absent || !/^[1-9][0-9]{0,9}\n?$/.test(out)) return reject(new Error('listener_observation'));
    resolve();
  }));
}
async function refuses(Type, work) {
  try {
    await work();
  } catch (error) {
    if (error instanceof Type)return;
    throw error;
  }
  throw new Error('refusal_missing');
}
function completed(raw) {
  const body = decode(raw);
  assert(body?.status === 'ok' && body?.result?.status === 'completed');
}
async function cases(value) {
  const {inputs} = value;
  const configs = [value.writer_config, value.supervisor_config, value.reader_config].map(parse_pool_config);
  assert(configs.every(config => config.max_size === 1));
  const options = {
    deadline: now()+120, signal: controller.signal
  }, pools = configs.map(config => new PoolResource(config));
  const writer = new PostgresQdrantWriter(pools[0], inputs.config, inputs.instance_id);
  const supervisor = new ManagedQdrantSupervisor(value.binary, value.work_dir, inputs.instance_id, inputs.config);
  const verifier = new QdrantReconciliationVerifier(writer, supervisor);
  const recovery = new PostgresQdrantRecovery(pools[1], inputs.config, supervisor, verifier);
  const authority = new PostgresQdrantPublicationAuthority(writer, recovery);
  const transport = new ManagedQdrantPublicationTransport(supervisor);
  const allowed = async(scope, collection, document) => scope.tenant_id === inputs.scope.tenant_id
    && collection === inputs.stage.manifest.collection
    && [inputs.stage.manifest.document_id, inputs.ownerless_stage.manifest.document_id].includes(document);
  const security = new QdrantSecurityManager(writer, allowed);
  let hook = null;
  const manager = new QdrantPublicationManager(authority, transport, inputs.config, supervisor, async(...args) => {
    if (!await allowed(...args)) return false;
    const action = hook;
    hook = null;
    if (action) await action();
    return true;
  });
  const store = new PostgresQdrantSourceStore(pools[2], inputs.config);
  const handles = new Set();
  const observations = [];
  let address, httpCount = 0, armed = false, drops = 0, puts = 0, retiredKey, currentKey, droppedPoints, retiredResends = 0;
  const nativeRequest = http.request, target = '/collections/'+inputs.config.physical_collection+'/points?wait=true&ordering=strong';
  const scope = revision => ({
    ...inputs.scope, authorization_revision: revision
  });
  const ref = (intent, stage = inputs.stage) => ({
    collection: stage.manifest.collection, document_id: stage.manifest.document_id, intent_id: intent
  });
  const context = (intent, revision, stage = inputs.stage) => ({
    ...ref(intent, stage), scope: scope(revision), owner_token: OWNER
  });
  async function call(work) {
    const ledger = new ExecutionLedger({
      limits: {
        deadline_ms: 120000, max_attempts: 1, max_provider_calls: 0
      }, deadline: options.deadline
    });
    try {
      return await work(ledger);
    } finally {
      const state = ledger.snapshot();
      assert(state.attempts === 1 && state.provider_calls === 0 && state.pending === 0);
    }
  }
  const stage = record => call(book => manager.stage(record, inputs.scope, book, options));
  const converge = (record, revision, source = inputs.stage) => call(book => manager.converge_security(ref(record.intent_id, source), scope(revision), book, options));
  const commit = async(record, revision) => {
    const result = await call(book => security[record.action](record, scope(revision), book, options));
    assert(result.authority_committed && !result.replica_complete && !result.purge_complete);
    return result;
  };
  function update(number, previous = number-1, tombstoned = false) {
    return {
      ...structuredClone(inputs.security),
      action: tombstoned?'tombstone':'update_authorization',
      intent_id: tombstoned?'native-security-public-tombstone':'native-security-public-auth-'+number,
      expected_authorization_revision:'auth-'+previous,
      expected_mutation_epoch: previous,
      authorization: {
        ...structuredClone(inputs.security.authorization),
        authorization_revision:'auth-'+number,
        principal_ids: ['reader-b'],
        grant_ids: [],
        tag:'public-security-'+number,
        tombstoned
      }
    };
  }
  const row = result => [result.intent_id, result.operation, result.state, result.authority_committed, result.replica_complete, result.purge_complete];
  const complete = result => assert(result.operation === 'converge_security'
    && result.state === 'complete'
    && result.authority_committed
    && result.replica_complete
    && !result.purge_complete);
  const snapshot = (record, revision, source = inputs.stage) => writer.manager_snapshot(context(record.intent_id, revision, source), options);
  const nom = {
    point_id: inputs.expected_points[0].id, branch:'dense', score: 1, score_kind:'cosine_similarity', score_direction:'higher_is_better', verification:'UNVERIFIED', payload: structuredClone(inputs.expected_points[0].payload)
  };
  const request = parse_request({
    query:'native source verification', collection: inputs.stage.manifest.collection
  });
  async function source(revision, principal = inputs.scope.principal_id) {
    const handle = store.open_request(request, {
      ...options, scope: {
        ...scope(revision), principal_id: principal
      }
    });
    handles.add(handle);
    try {
      const result = await handle.fetch_candidate(nom, {
        max_source_bytes: 16777216, include_source: true
      });
      if (result.state === 'verified') {
        const canonical = Buffer.from(inputs.stage.canonical_text,'utf8'), member = inputs.stage.manifest.members.find(item => item.point_id === nom.point_id), excerpt = canonical.subarray(member.start_byte, member.end_byte);
        assert(result.binding && result.evidence.text === new TextDecoder('utf-8', {
          fatal: true
        }).decode(excerpt)
          && result.evidence.source_sha256 === hash(canonical)
          && result.evidence.text_sha256 === hash(excerpt)
          && result.private_source.canonical_text === inputs.stage.canonical_text);
      }
      else assert(result.state === 'unavailable'
        && result.binding === null
        && result.evidence === null
        && result.private_source === null
        && result.source_bytes === 0);
      return {
        handle, result
      };
    } catch (error) {
      await handle.close();
      handles.delete(handle);
      throw error;
    }
  }
  async function closeSource(pair) {
    await pair.handle.close();
    handles.delete(pair.handle);
  }
  async function journal(intent, pendingOnly = false) {
    return pools[1].withLease(options, async client => {
      await client.query({text:'BEGIN',values:[],rowMode:'array'});
      try {
        await client.query({text:"SELECT set_config('cragkit_qdrant.backend_instance_id',$1,true)",values:[inputs.instance_id],rowMode:'array'});
        const result = await client.query({text:'SELECT state,completion_sha256 FROM cragkit_qdrant.dispatch_journal WHERE instance_id=$1 AND tenant_id=$2 AND collection=$3 AND document_id=$4 AND intent_id=$5'+(pendingOnly ? " AND state<>'settled'" : '')+' ORDER BY sequence LIMIT 9',
          values:[inputs.instance_id,inputs.scope.tenant_id,inputs.stage.manifest.collection,inputs.stage.manifest.document_id,intent],rowMode:'array'});
        await client.query({text:'COMMIT',values:[],rowMode:'array'});
        return result.rows;
      } catch (error) {
        await client.query({text:'ROLLBACK',values:[],rowMode:'array'});
        throw error;
      }
    });
  }
  async function physical(method, path, key, body) {
    assert(typeof key === 'string' && /^[0-9a-f]{64}$/.test(key));
    const endpoint = new URL(address), encoded = body === undefined ? undefined : Buffer.from(JSON.stringify(body));
    assert(endpoint.protocol === 'http:' && endpoint.hostname === '127.0.0.1' && endpoint.origin === address);
    return new Promise((resolve,reject) => {
      const request = nativeRequest({hostname:'127.0.0.1',port:Number(endpoint.port),method,path,agent:false,
        signal:options.signal,headers:{'api-key':key,...(encoded ? {'content-type':'application/json','content-length':encoded.length} : {})}}, response => {
        const chunks = []; let size = 0;
        response.on('data',chunk => { size += chunk.length; if(size > 1048576) request.destroy(new ProviderUnavailable()); else chunks.push(chunk); });
        response.on('end',() => resolve({status:response.statusCode,body:Buffer.concat(chunks)}));
        response.on('error',reject);
      });
      request.setTimeout(Math.max(1,Math.min(5000,(options.deadline-now())*1000)),() => request.destroy(new ProviderUnavailable()));
      request.on('error',reject);
      request.end(encoded);
    });
  }
  function mark(result) {
    observations.push(row(result));
    step++;
  }
  http.request = function(requestOptions, callback) {
    httpCount++;
    if (requestOptions?.headers?.['api-key']) currentKey = requestOptions.headers['api-key'];
    if (requestOptions?.method === 'PUT' && requestOptions.path === target) {
      puts++;
      if (retiredKey && currentKey === retiredKey) retiredResends++;
    }
    const drop = armed && requestOptions?.method === 'PUT' && requestOptions.path === target;
    if (drop) { armed = false; retiredKey = currentKey; }
    const outgoing = nativeRequest.call(this, requestOptions, incoming => {
      if (!drop) {
        callback(incoming);
        return;
      }
      const chunks = [];
      let size = 0, suppressed = false;
      const originalOnce = incoming.once;
      incoming.on('data', chunk => {
        size += chunk.length;
        if (size <= 1048576) chunks.push(Buffer.from(chunk));
      });
      originalOnce.call(incoming,'end', () => {
        try {
          assert(suppressed && size <= 1048576 && incoming.statusCode === 200);
          completed(Buffer.concat(chunks));
          drops++;
        } catch {
        }
        incoming.emit('error', new ProviderUnavailable());
      });
      incoming.once = function(event, listener) {
        if (event === 'end' && !suppressed) {
          suppressed = true;
          return this;
        }
        return originalOnce.call(this, event, listener);
      };
      try {
        callback(incoming);
      } finally {
        incoming.once = originalOnce;
      }
    });
    if (drop) {
      const originalWrite = outgoing.write, originalEnd = outgoing.end, chunks = [];
      let size = 0;
      const capture = chunk => {
        if (chunk === undefined || chunk === null || typeof chunk === 'function') return;
        const buffer = Buffer.from(chunk);
        size += buffer.length;
        assert(size <= 1048576);
        chunks.push(buffer);
      };
      outgoing.write = function(chunk, ...args) {
        capture(chunk);
        return originalWrite.call(this,chunk,...args);
      };
      outgoing.end = function(chunk, ...args) {
        capture(chunk);
        assert(size > 0);
        droppedPoints = decode(Buffer.concat(chunks)).points;
        return originalEnd.call(this,chunk,...args);
      };
    }
    return outgoing;
  };
  try {
    await supervisor.initialize({
      ...options, provision: async(admin, probe) => {
        await admin.request('PUT','/collections/'+inputs.config.physical_collection, {
          ...options, body: bytes(inputs.collection_config)
        });
        await admin.request('PUT','/collections/'+probe.collection, {
          ...options, body: bytes(probe.collection_config)
        });
        completed(await admin.request('PUT','/collections/'+probe.collection+'/points?wait=true&ordering=strong', {
          ...options, body: bytes({
            points: [probe.point]
          })
        }));
      }
    });
    address = supervisor.identity().endpoint;
    await listener(address);
    for (const pool of pools) await pool.open();
    await manager.initialize(options);
    await security.initialize(options);
    await store.initialize(options);
    await stage(inputs.stage);
    const published = await call(book => manager.publish(ref(inputs.stage.intent.intent_id), inputs.scope, book, options));
    assert(published.published);
    const second = structuredClone(inputs.second_stage);
    second.intent.expected_active_generation_id = inputs.stage.manifest.generation_id;
    await stage(second);
    const first = structuredClone(inputs.security);
    first.authorization.principal_ids = [inputs.scope.principal_id];
    first.authorization.grant_ids = [];
    const authorityResult = await commit(first,'auth-1');
    assert(authorityResult.authority_committed && !authorityResult.replica_complete);
    const projection = security_projection_data(await writer.project_security(context(first.intent_id,'auth-2'),options),writer);
    assert(projection.generations.length === 2 && projection.point_ids.length === 4);
    const firstResult = await converge(first,'auth-2');
    complete(firstResult);
    mark(firstResult);
    const retained = await source('auth-2');
    assert(retained.result.state === 'verified');

    const before = await snapshot(first,'auth-2');
    const count = httpCount;
    const retry = await converge(first,'auth-2');
    assert(same(retry, firstResult) && same(await snapshot(first,'auth-2'), before) && httpCount === count);
    mark(retry);

    const original = await writer.manager_snapshot(context(inputs.stage.intent.intent_id,'auth-2'), options);
    const revokedStage = structuredClone(second);
    revokedStage.intent.intent_id = 'native-security-revocation-between-stages';
    revokedStage.intent.expected_authorization_revision = 'auth-2';
    revokedStage.intent.expected_mutation_epoch = 2;
    revokedStage.intent.initial_authorization = null;
    const stagedRevocation = await call(book => manager.stage(revokedStage, scope('auth-2'), book, options));
    assert(stagedRevocation.state === 'staged' && !stagedRevocation.published);
    const third = update(3);
    const authorityCount = httpCount;
    await commit(third,'auth-2');
    assert(httpCount === authorityCount);
    const thirdProjection = security_projection_data(await writer.project_security(context(third.intent_id,'auth-3'),options),writer);
    assert(thirdProjection.point_ids.length === 4);
    const thirdDrops = drops, thirdPuts = puts;
    armed = true;
    await refuses(ProviderUnavailable, () => converge(third,'auth-3'));
    const thirdPending = await snapshot(third,'auth-3');
    assert(drops === thirdDrops+1 && puts === thirdPuts+1 && !armed
      && thirdPending.pending && thirdPending.backend.state === 'recovery_blocked'
      && thirdPending.document.authorization_revision === 'auth-3'
      && thirdPending.intent.authority_committed && !thirdPending.intent.replica_complete
      && thirdPending.owner
      && same(await journal(thirdPending.owner.intent_id,true), [['unknown',null]])
      && Array.isArray(droppedPoints)
      && same(droppedPoints.map(point => point.id).sort(),[...thirdProjection.point_ids].sort())
      && droppedPoints.every(point => same(point.payload,thirdProjection.points.find(expected => expected.point_id === point.id)?.payload)
        && point.payload.authorization_revision === 'auth-3' && point.vector?.dense));
    const thirdGeneration = supervisor.control_binding().credential_generation;
    const thirdKey = retiredKey, thirdRetiredResends = retiredResends;
    const released = await retained.handle.release(retained.result.binding, {
      purpose:'provider', max_source_bytes: 16777216, include_source: true
    });
    assert(released.state === 'unavailable' && released.binding === null && released.evidence === null
      && released.private_source === null && released.source_bytes === 0);
    const revokedRelease = await retained.handle.release(retained.result.binding, {
      purpose:'final', max_source_bytes:16777216, include_source:true
    });
    assert(revokedRelease.state === 'unavailable' && revokedRelease.binding === null
      && revokedRelease.evidence === null && revokedRelease.private_source === null
      && revokedRelease.source_bytes === 0);
    await closeSource(retained);
    const denied = await source('auth-3');
    assert(denied.result.state === 'unavailable');
    await closeSource(denied);
    const permitted = await source('auth-3','reader-b');
    assert(permitted.result.state === 'verified');
    await closeSource(permitted);
    const thirdResult = await converge(third,'auth-3');
    complete(thirdResult);
    const history = await writer.manager_snapshot(context(inputs.stage.intent.intent_id,'auth-3'), options);
    assert(same(history.intent, original.intent)
      && history.document.active_generation_id === inputs.stage.manifest.generation_id);
    mark(thirdResult);
    const thirdRecovered = await snapshot(third,'auth-3');
    const thirdJournal = await journal(thirdPending.owner.intent_id);
    assert(supervisor.control_binding().credential_generation !== thirdGeneration
      && currentKey !== thirdKey
      && thirdRecovered.backend.state === 'open'
      && thirdJournal.length > 0 && thirdJournal.every(entry => entry[0] === 'settled' && typeof entry[1] === 'string')
      && drops === thirdDrops+1 && retiredResends === thirdRetiredResends
      && !(await snapshot(third,'auth-3')).pending);
    assert((await physical('GET',target.split('?')[0],thirdKey)).status === 401);
    const readback = await physical('POST',target.split('?')[0],currentKey,
      {ids:thirdProjection.point_ids,with_payload:true,with_vector:true});
    const replicas = decode(readback.body);
    assert(readback.status === 200 && replicas.status === 'ok' && Array.isArray(replicas.result)
      && same(replicas.result.map(point => point.id).sort(), [...thirdProjection.point_ids].sort())
      && replicas.result.every(point => point.payload.authorization_revision === 'auth-3'
        && same(point.payload.principal_ids,['reader-b']) && same(point.payload.grant_ids,[])
        && same(point.payload,thirdProjection.points.find(expected => expected.point_id === point.id)?.payload)));
    observations.push(['acl_replica_ack_lost','auth-3','recovery_blocked','unknown','unavailable','unavailable',0,1,0,true,true]);
    step++;

    const revokedBefore = await snapshot(revokedStage.intent,'auth-3');
    const revokedCount = httpCount, revokedPuts = puts;
    await refuses(UnauthorizedScope, () => call(book => manager.publish(ref(revokedStage.intent.intent_id), scope('auth-2'), book, options)));
    const revokedPublication = await call(book => manager.publish(ref(revokedStage.intent.intent_id), {
      ...scope('auth-3'), principal_id:'reader-b'
    }, book, options));
    const revokedAfter = await snapshot(revokedStage.intent,'auth-3');
    assert(revokedBefore.intent.state === 'staged'
      && revokedPublication.state === 'denied' && !revokedPublication.published
      && revokedAfter.intent.state === 'denied'
      && same(revokedAfter.document, revokedBefore.document)
      && revokedAfter.document.active_generation_id === inputs.stage.manifest.generation_id
      && httpCount === revokedCount && puts === revokedPuts);
    const revokedFresh = await source('auth-3');
    assert(revokedFresh.result.state === 'unavailable');
    await closeSource(revokedFresh);
    const currentReader = await source('auth-3','reader-b');
    assert(currentReader.result.state === 'verified');
    await closeSource(currentReader);
    observations.push(['revocation_between_stages','unauthorized_scope','denied',true,0,0,'unavailable','unavailable','verified']);
    step++;

    const fourth = update(4);
    await commit(fourth,'auth-3');
    const fourthDrops = drops;
    armed = true;
    await refuses(ProviderUnavailable, () => converge(fourth,'auth-4'));
    const pending = await snapshot(fourth,'auth-4');
    assert(drops === fourthDrops+1
      && !armed
      && pending.pending
      && pending.backend.state === 'recovery_blocked'
      && !pending.intent.replica_complete);
    const generation = supervisor.control_binding().credential_generation;
    const fourthResult = await converge(fourth,'auth-4');
    complete(fourthResult);
    assert(supervisor.control_binding().credential_generation !== generation && drops === fourthDrops+1);
    mark(fourthResult);
    observations.push(['source','verified','unavailable','unavailable','verified']);
    step++;

    await stage(inputs.ownerless_stage);
    const ownerless = structuredClone(inputs.ownerless_security);
    ownerless.authorization.principal_ids = [inputs.scope.principal_id];
    ownerless.authorization.grant_ids = [];
    await commit(ownerless,'auth-1');
    const admission = await writer.admit_publication(context(inputs.ownerless_stage.intent.intent_id,'auth-2', inputs.ownerless_stage), options);
    assert(admission.intent.state === 'denied' && admission.owner === null);
    const ownerlessResult = await converge(ownerless,'auth-2', inputs.ownerless_stage);
    complete(ownerlessResult);
    mark(ownerlessResult);

    const fifth = update(5), sixth = update(6);
    await commit(fifth,'auth-4');
    hook = () => commit(sixth,'auth-5');
    await refuses(UnauthorizedScope, () => converge(fifth,'auth-5'));
    const drift = await snapshot(sixth,'auth-6');
    assert(drift.document.authorization_revision === 'auth-6'
      && drift.document.active_generation_id === inputs.stage.manifest.generation_id);
    complete(await converge(sixth,'auth-6'));
    observations.push(['drift','unauthorized_scope','auth-6']);
    step++;

    const seventh = update(7), tombstone = update(8, 7, true);
    await commit(seventh,'auth-6');
    hook = () => commit(tombstone,'auth-7');
    await refuses(UnauthorizedScope, () => converge(seventh,'auth-7'));
    const tomb = await snapshot(tombstone,'auth-8');
    assert(tomb.document.tombstoned
      && tomb.intent.authority_committed
      && !tomb.intent.replica_complete
      && !tomb.intent.purge_complete);
    const unavailable = await source('auth-8','reader-b');
    assert(unavailable.result.state === 'unavailable');
    await closeSource(unavailable);
    observations.push(['tombstone','unauthorized_scope','unavailable', true, false]);
    step++;
    return {
      runtime:'typescript',
      checks: CHECKS,
      proof_scope:'native_public_security_convergence_only',
      semantic_witness_sha256: hash(Buffer.from(JSON.stringify(['cragkit.qdrant.public-security.v1', observations]),'utf8'))
    };
  } finally {
    http.request = nativeRequest;
    let failed = false;
    const deadline = now()+12;
    const resources = [...handles, store, manager, security, transport, recovery, verifier, writer, ...pools, supervisor];
    for (const owner of resources) {
      try {
        if (typeof owner.close === 'function') {
          await bounded(Promise.resolve().then(() => owner.close()), {
            deadline: Math.max(now()+.001, Math.min(now()+8, deadline))
          });
        }
      } catch {
        failed = true;
      }
    }
    if (address) {
      try {
        await listener(address, true);
      } catch {
        failed = true;
      }
    }
    if (failed) throw new Error('cleanup_failed');
  }
}
try {
  const value = await bounded(input(), {
    deadline: now()+5, signal: controller.signal
  });
  reading = false;
  process.stdout.write(JSON.stringify(await cases(value))+'\n');
} catch (error) {
  let name = 'internal';
  try {
    if (ERRORS.has(error?.name)) name = error.name;
  }
  catch {
  }
  process.stdout.write(JSON.stringify({
    ok: false, step, error: name
  })+'\n');
  process.exitCode = 1;
} finally {
  process.removeListener('SIGTERM', cancel);
  process.removeListener('SIGINT', cancel);
}
