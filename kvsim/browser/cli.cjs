#!/usr/bin/env node
'use strict';
const fs=require('node:fs'),path=require('node:path'),K=require('./core.js');
const [input,output,...capacities]=process.argv.slice(2);
if(!input||!output){console.error('Usage: node kvsim/browser/cli.cjs CONFIG_OR_SCENARIO.json OUTPUT_DIR [GiB ...]');process.exit(2)}
try{
 const settings=JSON.parse(fs.readFileSync(input,'utf8'));
 const plan=JSON.parse(fs.readFileSync(path.join(__dirname,'../../output/ascend-handoff/Ascend910C_KV_Replay_425/workload/reference-plan.json'),'utf8'));
 const body={settings};if(capacities.length)body.capacities=capacities.map(Number);
 const {results}=K.run(body,plan);
 for(const [i,r] of results.entries()){
  const dir=results.length===1?output:path.join(output,String(i+1)+'-'+r.profile.kv_bytes/2**30+'GiB');fs.mkdirSync(dir,{recursive:true});
  for(const [name,value] of Object.entries({scenario:r.scenario,result:r,summary:r.summary,resolved_config:r.profile}))fs.writeFileSync(path.join(dir,name+'.json'),JSON.stringify(value));
  const keys=['request_id','session','p_domain','p_input_tokens','candidate_tokens','adopted_cached_tokens','input_compute_tokens','status'];
  const quote=v=>'"'+String(v??'').replaceAll('"','""')+'"';fs.writeFileSync(path.join(dir,'requests.csv'),[keys.join(','),...r.requests.map(row=>keys.map(k=>quote(row[k])).join(','))].join('\n'));
  console.log(JSON.stringify({output:dir,status:r.status,...r.summary}));
 }
}catch(e){console.error(JSON.stringify({status:e instanceof K.ResourceLimit?'resource_limit':e instanceof K.Unsupported?'unsupported':'invalid_input',error:e.message}));process.exitCode=1}
