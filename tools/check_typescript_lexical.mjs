/** Native read-only child of the explicit empty-target fixture. */
import { readFileSync,lstatSync } from 'node:fs';
import { PoolResource,parse_pool_config,now } from '../packages/typescript/dist/postgres-pool.js';
import { PostgresSession } from '../packages/typescript/dist/postgres-session.js';
import { CragkitError } from '../packages/typescript/dist/errors.js';
import { parse_scope,parse_request } from '../packages/typescript/dist/contracts.js';
class CheckError extends Error {}
const requireCheck=(condition,code)=>{if(!condition)throw new CheckError(code);};
function privateJSON(path){const stat=lstatSync(path);requireCheck(stat.isFile()&&stat.uid===process.getuid()&&(stat.mode&0o077)===0,'lexical_private_file');return JSON.parse(readFileSync(path,'utf8'));}
try {
  const args=process.argv.slice(2);requireCheck(args.length===3&&args[0]==='--allow-lexical-checks','lexical_explicit_authorization');
  const resource=new PoolResource(parse_pool_config(privateJSON(args[1])));const fixture=privateJSON(args[2]);
  const scopes=fixture.scopes.map(parse_scope);const session=new PostgresSession(resource);
  const query=async(scope,filters=[],limit=100)=>session.transaction(parse_request({query:'Café',collection:fixture.collection,required_filters:filters}),
    {scope,deadline:now()+8},handle=>handle.lexical_candidates({limit}));
  try {
    await resource.open();
    for(let index=0;index<scopes.length;index++) {
      const scope=scopes[index],expected=fixture.expected[index];
      requireCheck(JSON.stringify(await query(scope))===JSON.stringify(expected),'lexical_node_python_parity');
      requireCheck(JSON.stringify(await query(scope,[],1))===JSON.stringify(expected.slice(0,1)),'lexical_node_limit');
      requireCheck(JSON.stringify(await query(scope,[{op:'eq',field:'document_id',value:'tie-document'}],1))===JSON.stringify(expected.filter(item=>item.document_id==='tie-document')),'lexical_node_filter');
      requireCheck((await query(scope,[{op:'eq',field:'document_id',value:"missing' OR TRUE --"}])).length===0,'lexical_node_injection');
    }
    for(const changes of [{principal_id:'unauthorized-principal',grant_ids:[]},{authorization_revision:'stale'}])
      requireCheck((await query(parse_scope({...scopes[0],...changes}))).length===0,'lexical_node_scope');
    process.stdout.write(JSON.stringify({state:'passed',checks:['node_scoped_fts_matches_python_filters_limit_authorization_tombstone_readiness']})+'\n');
  } finally {await resource.close();}
} catch(error) {
  const code=error instanceof CragkitError?'lexical_node_'+error.code:error instanceof CheckError&&/^[a-z_]+$/.test(error.message)?error.message:'lexical_node_failed';
  process.stdout.write(JSON.stringify({state:'failed',code})+'\n');process.exitCode=1;
}
