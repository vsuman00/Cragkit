/** Restricted native profile-5 admission against the parent's disposable DB. */
import {PoolResource,parse_pool_config,now} from '../packages/typescript/dist/postgres-pool.js';
import {PostgresQdrantWriter} from '../packages/typescript/dist/qdrant-writer.js';
import {PostgresQdrantSourceStore} from '../packages/typescript/dist/qdrant-source.js';

let step='input';
let writerResource,readerResource,writer,source;
try{
  const chunks=[];let size=0;
  for await(const part of process.stdin){
    size+=part.length;if(size>65536)throw new Error('input_too_large');chunks.push(part);
  }
  const value=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks)));
  if(!value||Object.getPrototypeOf(value)!==Object.prototype
    ||JSON.stringify(Object.keys(value).sort())!==JSON.stringify(['writer_config','reader_config','config','instance_id'].sort())){
    throw new Error('input_shape');
  }
  const options={deadline:now()+15};
  step='writer';
  writerResource=new PoolResource(parse_pool_config(value.writer_config));
  writer=new PostgresQdrantWriter(writerResource,value.config,value.instance_id);
  await writerResource.open();await writer.initialize(options);
  await writer.close();await writerResource.close();writer=null;writerResource=null;
  step='reader';
  readerResource=new PoolResource(parse_pool_config(value.reader_config));
  source=new PostgresQdrantSourceStore(readerResource,value.config);
  await readerResource.open();await source.initialize(options);
  await source.close();await readerResource.close();source=null;readerResource=null;
  process.stdout.write(JSON.stringify({ok:true,checks:['node_restricted_writer_profile5','node_restricted_reader_profile5']})+'\n');
}catch(error){
  process.stdout.write(JSON.stringify({ok:false,step,error:error?.name??'internal'})+'\n');
  process.exitCode=1;
}finally{
  await Promise.allSettled([source?.close(),readerResource?.close(),writer?.close(),writerResource?.close()]);
}
