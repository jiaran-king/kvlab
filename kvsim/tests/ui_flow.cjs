/* DOM/Worker unit harness, not a browser acceptance claim. */
'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),K=require('../browser/core.js');
class Element{
 constructor(){this.value='';this.textContent='';this.disabled=false;this.children=[];this.files=[];this.className='';this.classList={toggle(){},add(){}};}
 addEventListener(){} append(x){this.children.push(x)} replaceChildren(){this.children=[]} close(){} showModal(){} remove(){} click(){}
}
const html=fs.readFileSync('kvsim/KVLab.html','utf8'),els=new Map();
for(const match of html.matchAll(/id="([^"]+)"[^>]*>/g)){const e=new Element();e.value=match[0].match(/value="([^"]*)"/)?.[1]??'';els.set(match[1],e);}
for(const [id,v] of Object.entries({workload:'synthetic',block:'128',route:'spread',chunk:'8192',executionMode:'fixed',metricView:'hit',domainView:'0'}))els.get(id).value=v;
els.get('simCore').textContent=fs.readFileSync('kvsim/browser/core.js','utf8');els.get('builtinPlan').textContent=html.match(/<script id="builtinPlan" type="application\/json">([\s\S]*?)<\/script>/)[1];
const doc={getElementById:id=>els.get(id),querySelector:()=>new Element(),createElement:()=>new Element(),body:new Element()};
class WorkerStub{postMessage(data){queueMicrotask(()=>{try{this.onmessage({data:K.run(data.body,data.plan)})}catch(e){this.onmessage({data:{error:e.message,status:'invalid_input'}})}})}terminate(){}}
const context=vm.createContext({document:doc,KVSim:K,structuredClone,Blob,URL:{createObjectURL:()=>'',revokeObjectURL(){}},Worker:WorkerStub,setTimeout:()=>0,clearTimeout(){},console});
for(const script of html.matchAll(/<script>([\s\S]*?)<\/script>/g))vm.runInContext(script[1],context);
const get=id=>els.get(id);
(async()=>{
 assert(get('loadPreview').textContent.includes('16'));
 await vm.runInContext('run(false)',context);assert.equal(get('hit').textContent,'52.39%');
 get('clearRuns').onclick();assert.equal(get('hit').textContent,'—');assert(get('downloadResult').disabled);
 get('workload').value='importWorkload';get('workload').onchange();
 const workload=fs.readFileSync('output/kvsim/v03/replay-small-workload.json','utf8');get('file').files=[{name:'small.json',text:async()=>workload}];await get('file').onchange();assert(get('filename').textContent.includes('15 条请求'));assert(!get('domains').disabled);
 await vm.runInContext('run(false)',context);assert.equal(get('completed').textContent,'15 / 15');
 get('file').files=[{name:'bad.json',text:async()=>'{bad'}];await get('file').onchange();await vm.runInContext('run(false)',context);assert(get('message').textContent.includes('请先成功导入'));
 get('workload').value='importScenario';get('workload').onchange();assert(get('domains').disabled);get('file').files=[{name:'scenario.json',text:async()=>fs.readFileSync('output/kvsim/v03/small-sweep/1-8GiB/scenario.json','utf8')}];await get('file').onchange();await vm.runInContext('run(false)',context);assert.equal(get('completed').textContent,'15 / 15');
 assert.equal(get('domains').value,'4');
 const frozen=JSON.parse(fs.readFileSync('output/kvsim/v03/small-sweep/1-8GiB/scenario.json'));
 assert.equal(Number(get('capacity').value),frozen.config.kv_gib);assert.equal(Number(get('sessionConcurrency').value),frozen.execution.session_concurrency);
 get('workload').value='importWorkload';get('workload').onchange();
 const c={schema:'kvlab-conditions/v1',config:{profile:'ascend-a3-continuous',kv_gib:12,block_size:64,max_input_tokens:90000},p_domains:1,routing_mode:'p0',routing:{},execution_mode:'workload',execution:{concurrency:2,p_slots:1,chunk_tokens:4096,step_budget:8192,transfer_ticks:2,decode_ticks:3,session_concurrency:6,seconds_per_tick:0.5,decode_tokens_per_tick:128},capacities:[12,16,24]};
 get('conditionsFile').files=[{text:async()=>JSON.stringify(c)}];await get('conditionsFile').onchange();assert(get('conditionsNote').textContent.includes('已导入'));
 let prevented=false;await get('conditionsDrop').ondrop({preventDefault(){prevented=true},stopPropagation(){},dataTransfer:{files:[{name:'dragged.json',text:async()=>JSON.stringify(c)}]}});assert(prevented);assert(get('conditionsNote').textContent.includes('dragged.json'));
 await get('conditionsDrop').ondrop({preventDefault(){},stopPropagation(){},dataTransfer:{files:[{name:'bad.json',text:async()=>'{bad'}]}});assert(get('conditionsNote').textContent.includes('失败'));assert.equal(get('capacity').value,'12');
 get('file').files=[{text:async()=>workload}];await get('file').onchange();
 assert.equal(get('sessionConcurrency').value,'6');assert.equal(get('concurrency').value,'2');
 assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(readConditions())',context)),c);
 const effective=JSON.parse(vm.runInContext('JSON.stringify(KVSim.compileScenario(settings()))',context));
 assert.equal(effective.p_domains,1);assert(effective.requests.every(r=>r.p_domain===0));assert.equal(effective.execution.chunk_tokens,4096);assert.equal(effective.execution.step_budget,8192);assert.equal(effective.config.kv_gib,12);
 const before=vm.runInContext('JSON.stringify(readConditions())',context);
 get('conditionsFile').files=[{text:async()=>JSON.stringify({...c,p_domains:0})}];await get('conditionsFile').onchange();assert(get('conditionsNote').textContent.includes('失败'));assert.equal(vm.runInContext('JSON.stringify(readConditions())',context),before);
 get('capacity').value='16';get('exportConditions').onclick();assert(get('conditionsNote').textContent.includes('已导出'));
 get('removeRun').onclick();assert(!get('clearRuns').disabled);get('clearRuns').onclick();assert(get('removeRun').disabled);assert.equal(get('comparison').children.length,0);
 console.log('PASS HTML controller in DOM harness: preview, run, cleanup, workload import, stale-import rejection, frozen scenario locks and rerun');
})().catch(e=>{console.error(e);process.exitCode=1});
