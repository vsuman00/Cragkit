import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {pack_and_assess} from '../dist/evidence.js';
import {pack_evidence} from '../dist/packing.js';
import {Cl100kCounter} from '../dist/context.js';
import {InvalidRequest,DeadlineExceeded} from '../dist/errors.js';
const sha=value=>createHash('sha256').update(value).digest('hex');
const query='Which requirements are supported?';
function pair(id,text){const source={collection:'c',document_id:id,revision_id:'r',source_sha256:sha(text),text};const item={evidence_id:id,collection:'c',document_id:id,revision_id:'r',chunk_id:id,source_locator:'s',start_byte:0,end_byte:Buffer.byteLength(text),text,source_sha256:sha(text),text_sha256:sha(text)};return {source,item};}
const anchor=item=>Object.fromEntries(['collection','document_id','revision_id','source_sha256','start_byte','end_byte','text'].map(key=>[key,item[key]]).concat([['claim_id','support']]));
const facet=(id,item)=>({facet_id:id,question:id,required:true,absence:'missing',anchors:[anchor(item)]});
const policy=facets=>({policy_id:'reviewed',version:'1',query_sha256:sha(query),facets});
const options=extra=>({deadline:performance.now()/1000+5,max_tokens:10000,reserve:0,surrounding_bytes:0,...extra});

test('post-packing assessment never keeps support from omitted seeds',async()=>{
  const a=pair('a','alpha'),b=pair('b','bravo');
  const single=await pack_evidence([a.item],[a.source],options());
  const result=await pack_and_assess(query,[a.item,b.item],[a.source,b.source],options({max_tokens:single.total_tokens,policy:policy([facet('a',a.item),facet('b',b.item)])}));
  assert.deepEqual(result.evidence.map(item=>item.evidence_id),['a']);
  assert.deepEqual(result.facets.map(f=>f.state),['supported','missing']);
  assert.equal(result.status,'partial');assert.equal(result.rebalance_count,0);
});

test('one rebalance improves required support and ties retain the original',async()=>{
  const a=pair('a','alpha'),b=pair('b','bravo');
  const single=await pack_evidence([a.item],[a.source],options());
  for(const improved of [false,true]){
    const facets=[facet('a',a.item),facet('b',b.item),...(improved?[facet('c',b.item)]:[])];
    const result=await pack_and_assess(query,[a.item,b.item],[a.source,b.source],options({max_tokens:single.total_tokens,policy:policy(facets),rebalance:true}));
    assert.equal(result.rebalance_count,1);assert.deepEqual(result.evidence.map(item=>item.evidence_id),[improved?'b':'a']);
    assert.equal(result.facets.filter(f=>f.state==='supported').length,improved?2:1);
  }
});

test('merged aliases are reassessed by exact anchor containment with strict counts',async()=>{
  const counter=await Cl100kCounter.create(new URL('../../../artifacts/tokenizers/cl100k_base.tiktoken',import.meta.url));
  try{
    const a=pair('a','é中文');
    const left={...a.item,end_byte:2,text:'é',text_sha256:sha('é')};
    const right={...a.item,evidence_id:'b',chunk_id:'b',start_byte:2,text:'中文',text_sha256:sha('中文')};
    const result=await pack_and_assess(query,[left,right],[a.source],options({counter,counting_mode:'strict',reserve:7,policy:policy([facet('f',a.item)])}));
    assert.equal(result.merged_count,1);assert.deepEqual(result.facets[0].evidence_ids,[result.evidence[0].evidence_id]);assert.deepEqual(result.aliases[result.evidence[0].evidence_id],['a','b']);
    assert.equal(result.status,'sufficient');assert.equal(result.context_tokens,counter.count(result.context));
    assert.equal(result.total_tokens,result.context_tokens+7);assert.ok(Object.isFrozen(result));
  }finally{counter.close();}
});

test('options, policy, sources and evidence are snapshotted before the first yield',async()=>{
  const a=pair('a','alpha'),configured=policy([facet('a',a.item)]),sources=[a.source],items=[a.item];
  const pending=pack_and_assess(query,items,sources,options({policy:configured,rebalance:true}));
  a.source.text='wrong';items.length=0;sources.length=0;configured.facets.length=0;
  const result=await pending;assert.equal(result.status,'sufficient');assert.equal(result.evidence[0].text,'alpha');
});

test('unknown helper fields, accessors and cancellation fail before packing',async()=>{
  let calls=0;
  await assert.rejects(pack_and_assess(query,[],[],{...options(),get policy(){calls++;return null;}}),InvalidRequest);
  assert.equal(calls,0);
  await assert.rejects(pack_and_assess(query,[],[],options({facet_evidence:[]})),InvalidRequest);
  await assert.rejects(pack_and_assess(query,[],[],options({rebalance:1})),InvalidRequest);
  await assert.rejects(pack_and_assess(query,[],[],options({deadline:0})),DeadlineExceeded);
  const a=pair('a','alpha'),controller=new AbortController();
  const pending=pack_and_assess(query,[a.item],[a.source],options({signal:controller.signal}));controller.abort();
  await assert.rejects(pending,{name:'AbortError'});
});
