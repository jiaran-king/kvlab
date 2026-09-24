'use strict';
const assert=require('node:assert/strict'),crypto=require('node:crypto'),K=require('../browser/core.js');
const hash=text=>crypto.createHash('sha256').update(text).digest('hex');
function reference(tokens,end,salt=''){let key=hash(JSON.stringify(['tokens-v1',salt]));for(let i=0;i<end;i+=128)key=hash(key+':'+JSON.stringify(tokens.slice(i,Math.min(i+128,end))));return key;}
const tokens=Array.from({length:10000},(_,i)=>(i*57)%129280);
for(const end of [0,1,8,127,128,129,255,256,4096,8192,9999,10000]){
 const a={tokens,cache_identity:'isolation'},b={tokens:[...tokens.slice(0,500),...tokens.slice(500)],cache_identity:'isolation'};
 assert.equal(K.prefixKey(a,end),reference(tokens,end,'isolation'));assert.equal(K.prefixKey(a,end),K.prefixKey(b,end));
 if(end)assert.notEqual(K.prefixKey(a,end),K.prefixKey({...a,tokens:[tokens[0]+1,...tokens.slice(1)]},end));
}
const before=K.compileScenario({workload:'custom',p_domains:1,execution_mode:'workload',requests:[{id:'a',session:'s',tokens:Array(8192).fill(1),output_tokens:0},{id:'b',session:'s',tokens:Array(8192).fill(1),output_tokens:0,send_after:'a',context_after:'a'}],config:{block_size:32}});
assert.equal(K.simulate(before).requests[1].adopted_cached_tokens,4096);before.requests[1].tokens[0]=2;assert.equal(K.simulate(before).requests[1].adopted_cached_tokens,0);
console.log('PASS prefix chain against node crypto, slicing identity, isolation and modified input cache invalidation');
