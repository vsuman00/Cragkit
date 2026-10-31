/** Label-blind synthetic encoder; no label, provider or model access. */
import {createHash} from 'node:crypto';
export function encode(text) {
  const values=Array(1536).fill(0);
  for(const token of text.toLowerCase().match(/[a-z0-9_]+/g)??[]){
    const index=createHash('sha256').update(token,'ascii').digest().readUInt32BE(0)%1536;
    values[index]+=1;
  }
  const norm=Math.sqrt(values.reduce((sum,value)=>sum+value*value,0));
  if(norm===0){values[0]=1;return values;}
  return values.map(value=>value/norm);
}
