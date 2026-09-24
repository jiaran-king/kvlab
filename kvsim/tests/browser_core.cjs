'use strict';
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),cp=require('node:child_process'),assert=require('node:assert/strict'),crypto=require('node:crypto'),vm=require('node:vm');
const K=require('../browser/core.js'),root=path.resolve(__dirname,'../..');
for(const text of ['', 'abc', '缓存😀'])assert.equal(K.sha256(text),crypto.createHash('sha256').update(text).digest('hex'));
const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'kvsim-parity-'));
try{
 cp.execFileSync('python3',['-m','kvsim.tests.browser_fixtures',path.join(tmp,'fixtures.json')],{cwd:root,timeout:60000});
 const cases=JSON.parse(fs.readFileSync(path.join(tmp,'fixtures.json'))),plan=JSON.parse(fs.readFileSync(path.join(root,'output/ascend-handoff/Ascend910C_KV_Replay_425/workload/reference-plan.json')));
 for(const [i,c] of cases.entries()){
  assert.deepEqual(K.compileScenario(c.settings,plan),c.scenario);
  const r=K.simulate(c.scenario);delete r.simulator_version;delete r.diagnostics;delete c.result.simulator_version;assert.deepEqual(r,c.result);console.log('PASS Python parity',i);
 }
 const html=fs.readFileSync(path.join(root,'kvsim/KVLab.html'),'utf8');
 assert(!/\bfetch\s*\(|\/api\/|<script[^>]+src=|<link[^>]+href=/i.test(html));
 const core=html.match(/<script id="simCore" type="text\/javascript">([\s\S]*?)<\/script>/)[1];
 assert.equal(core,fs.readFileSync(path.join(root,'kvsim/browser/core.js'),'utf8'));
 const embeddedPlan=JSON.parse(html.match(/<script id="builtinPlan" type="application\/json">([\s\S]*?)<\/script>/)[1]);assert.deepEqual(embeddedPlan,plan);
 for(const m of html.matchAll(/<script>([\s\S]*?)<\/script>/g))new vm.Script(m[1]);
 assert.throws(()=>K.resolve({tp:8}),K.Unsupported);
 const longSettings={config:{kv_gib:64,max_input_tokens:100000},p_domains:1,synthetic:{chains:1,rounds:2,first_tokens:100000,increment:4096,output_tokens:256}};
 assert.throws(()=>K.compileScenario(longSettings),K.Unsupported);
 delete longSettings.config.max_input_tokens;
 const longResult=K.simulate(K.compileScenario(longSettings));
 assert.equal(longResult.status,'complete');assert.equal(longResult.requests[1].p_input_tokens,104352);
 assert.equal(longResult.summary.input_compute_tokens+longResult.summary.adopted_cached_tokens,longResult.summary.p_input_tokens);
 assert.deepEqual(K.syntheticSummary({chains:3,rounds:4,first_tokens:20000,increment:2048,output_tokens:256,competitors:2}),{count:30,last:26912,total:641472});
 assert.throws(()=>K.compileScenario({synthetic:{chains:2001,rounds:1}}),K.ResourceLimit);
 assert.throws(()=>K.compileScenario({synthetic:{chains:1,rounds:1,first_tokens:100000001}}),K.ResourceLimit);
 console.log('PASS long inputs, explicit deployment limit, resource classification, workload preview');
 const defaultScenario=K.compileScenario({});assert.deepEqual(K.simulate(defaultScenario),K.simulate(JSON.parse(JSON.stringify(defaultScenario))));
 console.log('PASS hashing, offline bundle, UI syntax, unsupported settings, roundtrip');
}finally{fs.rmSync(tmp,{recursive:true,force:true})}
