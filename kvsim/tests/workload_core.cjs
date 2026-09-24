'use strict';
const assert=require('node:assert/strict'),K=require('../browser/core.js');
function node(id,session,after=null,wait=0){return {runtime_request_id:id,runtime_session_id:session,source_key:id,actor_id:'lead',actor_role:'lead',node_type:'request',tokens:Array(200).fill(7),input_tokens:200,output_tokens:0,cache_identity:'',content_source:'captured_tokens',send_after:after,context_after:after,context_mode:after?'append':'independent',effective_interval_seconds:wait};}
function workload(){return {schema:K.WORKLOAD_SCHEMA,metadata:{exporter_version:'test',source_trace:'test fixture',source_sha256:'test',agentinfer_commit:'test',planner_version:'test',model:'test',tokenizer_sha256:'test',prompt_template:'test',seed:0,replay_config:{},source_modules:{},content_source:'captured_tokens',time_unit:'seconds',session_concurrency:1,sessions:[{id:'a',launch_order:0,arrival_seconds:0},{id:'b',launch_order:1,arrival_seconds:0}],assumptions:['Test tokens; not historical input']},requests:[node('a1','a'),node('a2','a','a1',10),node('b1','b')]};}
assert.throws(()=>K.resolve({kv_bytes:1}),/保留块/);
const w=workload();assert.equal(K.inspectImport(w).kind,'workload');
for(const x of [{}, {tasks:[]}, {schema:'other'}, {schema:K.WORKLOAD_SCHEMA}])assert.throws(()=>K.inspectImport(x));
const s=K.compileScenario({workload:'replay_workload',data:w,execution:{seconds_per_tick:2,decode_ticks:0}}),r=K.simulate(s);assert.equal(r.status,'complete');
const event=(kind,id)=>r.executed_events.find(x=>x.kind===kind&&x.request_id===id);
assert.equal(event('ARRIVE','a2').tick-event('REQUEST_COMPLETE','a1').tick,5);
assert.equal(r.session_launches[1].tick,event('REQUEST_COMPLETE','a2').tick);
assert.deepEqual(K.simulate(JSON.parse(JSON.stringify(s))),r);
const fast=K.simulate(K.compileScenario({execution_mode:'workload',p_domains:1,synthetic:{chains:1,rounds:2}}));assert.deepEqual(fast.requests[1].steps.map(x=>x.compute_tokens),[5920]);
const bad=workload();bad.requests[1].tokens.pop();assert.throws(()=>K.validateWorkload(bad));
const timing=workload();timing.requests.splice(1,0,{runtime_request_id:'timer',runtime_session_id:'a',node_type:'timing_dependency',context_after:null,send_after:'a1',effective_interval_seconds:3,effective_duration_seconds:4});timing.requests[2].send_after='timer';
const tr=K.simulate(K.compileScenario(timing));assert.equal(tr.status,'complete');assert.equal(tr.summary.planned,3);assert(tr.executed_events.some(e=>e.kind==='TIMER_COMPLETE'));
const c=K.compileScenario({synthetic:{chains:1,rounds:1}});c.events=[{seq:0,tick:0,kind:'ARRIVE',request_id:c.requests[0].id},{seq:1,tick:0,kind:'CANCEL',request_id:c.requests[0].id}];assert.equal(K.simulate(c).status,'cancelled');
console.log('PASS workload validation, no fallback, wait conversion, session gating, timing nodes, dynamic cache progression, deterministic replay, cancellation');

const page=K.resolve({}).page_bytes_per_rank;
const base={p_domains:1,synthetic:{chains:1,rounds:2,first_tokens:20000,increment:2048,output_tokens:256,competitors:1}};
const low=K.simulate(K.compileScenario({...base,config:{kv_bytes:page*1475}}));
const high=K.simulate(K.compileScenario({...base,config:{kv_bytes:page*1500}}));
assert.equal(low.status,'complete');assert.equal(high.status,'complete');assert.equal(low.requests.at(-1).adopted_cached_tokens,0);assert.equal(high.requests.at(-1).adopted_cached_tokens,16384);
assert(low.requests.at(-1).explanation.some(x=>x.last_physical_replacement));assert.equal(high.per_p[0].replacements,0);
console.log('PASS controlled capacity eviction at 1475 vs 1500 physical blocks with exact replacement evidence');
