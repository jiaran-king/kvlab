'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto'),K=require('../browser/core.js');
const dir='output/kvsim/v03',digest=x=>crypto.createHash('sha256').update(JSON.stringify(x)).digest('hex');
const w=JSON.parse(fs.readFileSync(dir+'/replay425-request-admission-workload.json'));K.validateWorkload(w);assert.equal(w.requests.filter(r=>r.node_type==='request').length,425);assert.equal(w.metadata.sessions.length,6);
let frozen,rows=[];
for(const [i,cap] of [8,12,16,24].entries()){
 const r=JSON.parse(fs.readFileSync(`${dir}/replay425-request-admission-sweep/${i+1}-${cap}GiB/result.json`));if(cap===8){assert.equal(r.status,'infeasible_under_execution_rules');assert.equal(r.summary.completed,82);}else{assert.equal(r.status,'complete');assert.equal(r.summary.completed,425);}
 const scenario=r.scenario;
 for(const q of scenario.requests){const original=w.requests.find(x=>x.runtime_request_id===q.id);assert.deepEqual(q.tokens,original.tokens);assert.equal(q.send_after,original.send_after);assert.equal(q.context_after,original.context_after);assert.equal(q.wait_seconds,original.effective_interval_seconds);}
 const config={...scenario.config};delete config.kv_gib;delete config.kv_bytes;
 const key=digest({...scenario,config});if(frozen)assert.equal(key,frozen);else frozen=key;
 if(cap===16){assert.equal(digest(K.simulate(K.inspectImport(scenario).value)),digest(r));}
 rows.push({capacity:cap,status:r.status,completed:r.summary.completed,adopted:r.summary.adopted_cached_tokens,compute:r.summary.input_compute_tokens,ratio:r.summary.input_cache_fraction,workload_and_route_unchanged:true});
}
const small=JSON.parse(fs.readFileSync(dir+'/replay-small-workload.json'));assert.equal(K.inspectImport(small).kind,'workload');assert.equal(small.metadata.sessions.length,3);assert.equal(small.requests.length,15);
const sr=K.run({settings:small,capacities:[8,12]}).results;assert.deepEqual(K.simulate(K.inspectImport(JSON.parse(JSON.stringify(sr[0]))).value),sr[0]);
const report={full_replay:rows,roundtrip:'16 GiB entire result reproduced from exported scenario',second_trace:{requests:15,sessions:3,roundtrip:true},content_source:w.metadata.content_source};fs.writeFileSync(dir+'/acceptance.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
