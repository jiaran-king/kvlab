/* KVSim 0.3 — pure offline mechanism core; shared by HTML worker and Node CLI.
 * Source-derived rules and supported scope: ../RULES.md. No inference or network.
 */
const KVSim = (() => {
  'use strict';
  class Unsupported extends Error {}
  class Infeasible extends Error {}
  class ResourceLimit extends Error {}
  const floor = Math.floor, ceil = Math.ceil;
  const clone = x => JSON.parse(JSON.stringify(x));
  const integer = (x, min=0) => Number.isSafeInteger(x) && x >= min;
  const fail = message => { throw new Error(message); };
  const resourceLimit = message => { throw new ResourceLimit(message); };
  const range = (a,b) => Array.from({length:Math.max(0,b-a)},(_,i)=>a+i);
  const segment = (id,length) => ({id,start:0,length});
  const length = parts => parts.reduce((n,p)=>n+p.length,0);
  function canonical(parts) {
    const out=[];
    for(const p of parts) {
      if(Object.keys(p).sort().join(',')!=='id,length,start' || typeof p.id!=='string' || !integer(p.start) || !integer(p.length)) fail('Each segment needs a string id and nonnegative integer start/length');
      if(!p.length) continue;
      const prev=out[out.length-1];
      if(prev && prev.id===p.id && prev.start+prev.length===p.start) prev.length+=p.length;
      else out.push({id:p.id,start:p.start,length:p.length});
    }
    return out;
  }
  function prefix(parts,count) {
    const out=[];
    for(const p of parts) {
      const n=Math.min(count,p.length);
      if(n) out.push({id:p.id,start:p.start,length:n});
      count-=n;
      if(!count) break;
    }
    return canonical(out);
  }
  function tokenParts(tokens) {
    if(!Array.isArray(tokens) || tokens.some(x=>!integer(x))) fail('tokens must be nonnegative integers');
    return tokens.map(t=>segment('token:'+t,1));
  }
  // SHA-256 bounds retained key size even for captured token arrays. Identity is
  // the complete ordered prefix plus cache isolation, never a fragment name alone.
  const K=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
  function sha256(text) {
    const bytes=new TextEncoder().encode(text), size=ceil((bytes.length+9)/64)*64;
    const data=new Uint8Array(size);data.set(bytes);data[bytes.length]=128;
    const view=new DataView(data.buffer);view.setUint32(size-8,floor(bytes.length/0x20000000));view.setUint32(size-4,(bytes.length*8)>>>0);
    const h=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
    const w=new Int32Array(64),rotr=(x,n)=>(x>>>n)|(x<<(32-n));
    for(let offset=0;offset<size;offset+=64) {
      for(let i=0;i<16;i++) w[i]=view.getInt32(offset+4*i);
      for(let i=16;i<64;i++){const a=w[i-15],b=w[i-2];w[i]=(w[i-16]+(rotr(a,7)^rotr(a,18)^(a>>>3))+w[i-7]+(rotr(b,17)^rotr(b,19)^(b>>>10)))|0;}
      let [a,b,c,d,e,f,g,z]=h;
      for(let i=0;i<64;i++){const t1=(z+(rotr(e,6)^rotr(e,11)^rotr(e,25))+((e&f)^(~e&g))+K[i]+w[i])|0,t2=((rotr(a,2)^rotr(a,13)^rotr(a,22))+((a&b)^(a&c)^(b&c)))|0;z=g;g=f;f=e;e=(d+t1)|0;d=c;c=b;b=a;a=(t1+t2)|0;}
      [a,b,c,d,e,f,g,z].forEach((v,i)=>h[i]=(h[i]+v)|0);
    }
    return h.map(x=>(x>>>0).toString(16).padStart(8,'0')).join('');
  }
  function tokenPrefixKey(request,end,tokenPrefixes=new WeakMap()){
    const tokens=request.tokens;
    let chains=tokenPrefixes.get(request);
    if(!chains){chains=[sha256(JSON.stringify(['tokens-v1',request.cache_identity??'']))];tokenPrefixes.set(request,chains);}
    const chunks=floor(end/128);
    while(chains.length<=chunks){const start=(chains.length-1)*128;chains.push(sha256(chains.at(-1)+':'+JSON.stringify(tokens.slice(start,start+128))));}
    return end%128?sha256(chains[chunks]+':'+JSON.stringify(tokens.slice(chunks*128,end))):chains[chunks];
  }
  const inputLength=request=>request.tokens?request.tokens.length:length(request.parts);
  const prefixKey=(request,end)=>request.tokens?tokenPrefixKey(request,end):sha256(JSON.stringify([request.cache_identity??'',prefix(request.parts,end)]));
  function resolve(config={}) {
    const unknown=Object.keys(config).filter(k=>!['profile','block_size','tp','kv_bytes','kv_gib','retention','max_input_tokens'].includes(k));
    if(unknown.length) throw new Unsupported('Unsupported profile settings: '+unknown.join(', '));
    if(config.max_input_tokens!=null&&!integer(config.max_input_tokens,1)) fail('部署最大输入长度必须是正整数，或留空');
    const b=config.block_size??128;
    if(![32,64,128].includes(b)) throw new Unsupported('A3 profile supports block_size 32, 64, 128 only');
    if((config.profile??'ascend-a3-continuous')!=='ascend-a3-continuous') throw new Unsupported('Unknown runtime profile');
    if((config.tp??4)!==4) throw new Unsupported('First profile fixes TP4');
    const budget=config.kv_bytes??Math.trunc((config.kv_gib??16)*2**30);
    if(!integer(budget,1)) fail('KV budget must be positive integer bytes per rank');
    const pageBytes=1154*b*22;if(budget<pageBytes)fail('KV 预算不足以容纳预设的一个保留块');const retention=config.retention??b*128;
    if(retention!==b*128) throw new Unsupported('Supported combination: retention=128*block_size');
    const group=(name,kind,block,window=0,ratio=1,layers=0)=>({name,kind,block,window,ratio,layers});
    return {name:'DeepSeek-V4 Flash · A3 · continuous state · TP4',ascend_commit:'3281a5fc44ec344ba304c9161a3959d8649471f4',vllm_commit:'568afb3a13806beb53bb2e6bd518269357b237c0',profile:'ascend-a3-continuous',block_size:b,alignment:b*128,hash_block_size:b/16,retention,tp:4,kv_bytes:budget,page_bytes_per_rank:pageBytes,num_blocks:floor(budget/pageBytes),reserved_blocks:1,
      groups:[group('C4-KV+index','dense',b*4,0,4,21),group('C128-KV','dense',b*128,0,128,20),group('SWA-0','window',b,128,1,22),group('SWA-1','window',b,128,1,21),group('C4-state+index-state','window',b/16,8,1,21),group('C128-state','window',b/4,128,1,20)],
      scope:'Source-derived frozen preset; historical Ascend local patches and exact runtime layout not supplied. Not a hardware-fit prediction.'};
  }
  function syntheticSummary(settings={}) {
    const s={chains:4,rounds:4,first_tokens:20000,increment:2048,output_tokens:256,competitors:0,...settings};
    const names={chains:'会话数量',rounds:'每个会话的轮数',first_tokens:'首轮输入',increment:'每轮新增输入',output_tokens:'每轮输出',competitors:'两轮之间插入的竞争请求数'};
    for(const k of Object.keys(names))if(!integer(s[k],['chains','rounds','first_tokens'].includes(k)?1:0))fail(names[k]+'必须是'+(['chains','rounds','first_tokens'].includes(k)?'正整数':'非负整数'));
    const count=s.chains*(s.rounds+(s.rounds-1)*s.competitors);
    const last=s.first_tokens+(s.rounds-1)*(s.increment+s.output_tokens);
    const total=s.chains*(s.rounds*s.first_tokens+s.rounds*(s.rounds-1)/2*(s.increment+s.output_tokens)+(s.rounds-1)*s.competitors*s.first_tokens);
    if(![count,last,total].every(Number.isSafeInteger))fail('输入组合超出精确整数计算范围，请减小参数');
    return {count,last,total};
  }
  function synthetic(settings={}) {
    const defaults={chains:4,rounds:4,first_tokens:20000,increment:2048,output_tokens:256,competitors:0},s={...defaults,...settings};
    const stats=syntheticSummary(s);
    if(stats.count>2000)throw new ResourceLimit('预计 '+stats.count+' 条请求，超过工具单次上限 2,000 条');
    if(stats.total>100000000)throw new ResourceLimit('累计输入 '+stats.total+' token，超过工具单次上限 1 亿 token');
    const requests=[];
    for(let c=0;c<s.chains;c++) {
      const sid='chain-'+c;let previous=null,parts=[];
      for(let turn=0;turn<s.rounds;turn++) {
        const id=`${sid}/r${turn}`,context=previous;
        parts=previous?[...parts,segment(previous+'/output',s.output_tokens),segment(id,s.increment)]:[segment(id,s.first_tokens)];
        let send=previous;
        for(let j=0;j<(previous?s.competitors:0);j++){const cid=`${id}/competition-${j}`;requests.push({id:cid,session:sid,parts:[segment(cid,s.first_tokens)],output_tokens:s.output_tokens,send_after:send,context_after:null,context_mode:'independent',source_kind:'synthetic'});send=cid;}
        requests.push({id,session:sid,parts:canonical(parts),output_tokens:s.output_tokens,send_after:send,context_after:context,context_mode:context?'append':'independent',source_kind:'synthetic'});previous=id;
      }
    }
    return requests;
  }
  function agentinfer(plan,captures=null) {
    const requests=[],assumptions=[];
    for(const task of plan.tasks) {
      const known=new Map();
      for(const node of task.requests) {
        if(node.node_type!=='request') throw new Unsupported('Timing-only nodes need explicit event adaptation');
        const key=node.source_key,id=task.runtime_session_id+'/'+key,parent=node.context_after,n=node.planned_input_tokens;
        let parts,source;
        if(captures && Object.hasOwn(captures,key)){parts=tokenParts(captures[key]);source='captured_tokens';}
        else {let inherited=[];if(parent&&known.has(parent)){const p=known.get(parent);inherited=[...p.parts,segment(p.id+'/output',p.output_tokens)];}parts=prefix(inherited,n);parts.push(segment(id+'/synthetic',n-length(parts)));source='synthetic_from_plan';}
        const req={id,session:task.runtime_session_id,parts:canonical(parts),output_tokens:node.planned_output_tokens,send_after:node.send_after?task.runtime_session_id+'/'+node.send_after:null,context_after:parent?task.runtime_session_id+'/'+parent:null,context_mode:node.context_mode,source_kind:source,wait_ticks:0};known.set(key,req);requests.push(req);
      }
    }
    if(requests.some(r=>r.source_kind==='synthetic_from_plan'))assumptions.push('Historical plan lengths/dependencies; contents synthesized by prefix slicing, NOT captured inputs or actual trim semantics.');
    assumptions.push('Historical wait seconds are not hardware time: generated virtual ordering uses zero think ticks unless explicit events are imported.');
    return [requests,assumptions];
  }
  const WORKLOAD_SCHEMA='kvlab-replay-workload/v1';
  function validateWorkload(w){
    if(!w||w.schema!==WORKLOAD_SCHEMA)throw new Unsupported('请导入 kvlab-replay-workload/v1 或完整 scenario；原始 Replay plan 需要先导出');
    const m=w.metadata;
    if(!m||!Array.isArray(m.sessions)||!m.sessions.length||!Array.isArray(m.assumptions)||m.time_unit!=='seconds')fail('Workload metadata requires sessions, assumptions and time_unit=seconds');
    for(const k of ['exporter_version','source_trace','source_sha256','agentinfer_commit','planner_version','model','content_source','tokenizer_sha256','prompt_template'])if(typeof m[k]!=='string'||!m[k])fail('Missing workload metadata: '+k);
    if(!integer(m.seed)||!m.replay_config||typeof m.replay_config!=='object'||!m.source_modules||typeof m.source_modules!=='object')fail('Missing replay config, seed or source module identity');
    if(!integer(m.session_concurrency,1))fail('Invalid session_concurrency');
    if(!['captured_tokens','trace_driven_synthetic'].includes(m.content_source))throw new Unsupported('Unsupported workload content source');
    const sessions=new Set();
    for(const s of m.sessions){if(typeof s.id!=='string'||!s.id||sessions.has(s.id)||!integer(s.launch_order)||!Number.isFinite(s.arrival_seconds)||s.arrival_seconds<0)fail('Invalid workload session');sessions.add(s.id);}
    if(!Array.isArray(w.requests)||!w.requests.length)fail('Workload requires request nodes');
    if(w.requests.length>2000)resourceLimit('Workload 超过工具 2,000 个节点上限');
    const ids=new Map();let total=0;
    for(const r of w.requests){
      if(typeof r.runtime_request_id!=='string'||!r.runtime_request_id||ids.has(r.runtime_request_id))fail('Invalid or duplicate runtime request id');ids.set(r.runtime_request_id,r);
      if(!sessions.has(r.runtime_session_id))fail('Unknown runtime session');
      for(const k of ['send_after','context_after'])if(r[k]!==null&&typeof r[k]!=='string')fail('Missing or invalid '+k);
      if(!Number.isFinite(r.effective_interval_seconds)||r.effective_interval_seconds<0)fail('Invalid wait interval');
      if(r.node_type==='timing_dependency'){
        if(!Number.isFinite(r.effective_duration_seconds)||r.effective_duration_seconds<0||r.context_after!==null)fail('Invalid timing-only node');
      }else if(r.node_type==='request'){
        for(const k of ['source_key','actor_id','actor_role','context_mode','content_source'])if(typeof r[k]!=='string')fail('Missing request field '+k);
        if(!['none','independent','append','trim','reset'].includes(r.context_mode))throw new Unsupported('Unknown context mode');
        if(!Array.isArray(r.tokens)||!integer(r.input_tokens,1)||r.tokens.length!==r.input_tokens||r.tokens.some(t=>!integer(t)))fail('Input tokens do not match the declared content');
        if(!integer(r.output_tokens)||typeof r.cache_identity!=='string')fail('Invalid output count or cache identity');
        if(r.content_source!==m.content_source)fail('Mixed content provenance requires separate workloads');total+=r.input_tokens;
      }else throw new Unsupported('Unknown Replay node type');
    }
    if(total>100000000)resourceLimit('累计输入超过工具单次上限 1 亿 token');
    for(const r of w.requests)for(const k of ['send_after','context_after'])if(r[k]!==null){const p=ids.get(r[k]);if(!p||p.runtime_session_id!==r.runtime_session_id)fail('Unknown or cross-session dependency');if(k==='context_after'&&p.node_type!=='request')fail('Context cannot inherit a timing-only node');}
    const done=new Set();let changed=true;while(changed){changed=false;for(const r of w.requests)if(!done.has(r.runtime_request_id)&&[r.send_after,r.context_after].every(d=>d===null||done.has(d))){done.add(r.runtime_request_id);changed=true;}}if(done.size!==ids.size)fail('Dependency cycle');
    return w;
  }
  function inspectImport(value){
    if(value?.schema===WORKLOAD_SCHEMA){validateWorkload(value);return {kind:'workload',value:clone(value)};}
    const scenario=value?.scenario??value;
    if(scenario?.schema_version===1){validate(scenario);return {kind:'scenario',value:clone(scenario)};}
    throw new Unsupported('文件格式不支持：请导入冻结 Replay workload 或完整 scenario。不会回退到示例。');
  }
  function validate(s,checkEvents=true) {
    resolve(s.config);
    if(!integer(s.p_domains,1)||s.p_domains>16) fail('p_domains must be in 1..16');
    const reqs=s.requests;
    if(!Array.isArray(reqs)||reqs.length<1)fail('至少需要一条请求');
    if(reqs.length>2000)throw new ResourceLimit('请求数超过工具单次上限 2,000 条');
    const ids=new Set(reqs.map(r=>r.id));if(ids.size!==reqs.length)fail('Duplicate request id');
    if(reqs.reduce((n,r)=>n+inputLength(r),0)>100000000)resourceLimit('累计输入超过工具单次上限 1 亿 token');
    for(const r of reqs){if(r.tokens){if(!Array.isArray(r.tokens)||r.tokens.some(t=>!integer(t)))fail('Invalid actual token sequence');if(r.parts)fail('Use tokens or parts, not both');}else r.parts=canonical(r.parts);if(r.node_type!=='timing_dependency'&&!integer(inputLength(r),1))fail('输入长度必须是正整数');if(s.config.max_input_tokens!=null&&inputLength(r)>s.config.max_input_tokens)throw new Unsupported('请求 '+r.id+' 的输入为 '+inputLength(r)+' token，超过设定的部署最大输入 '+s.config.max_input_tokens+' token');if(!integer(r.output_tokens))fail('output_tokens must be nonnegative');if(!integer(r.p_domain)||r.p_domain>=s.p_domains)fail('Invalid P domain');for(const k of ['send_after','context_after'])if(r[k]!=null&&!ids.has(r[k]))fail('Unknown '+k+': '+r[k]);}
    const e=s.execution,keys=['concurrency','p_slots','chunk_tokens','step_budget','transfer_ticks','decode_ticks'];
    if(s.execution_mode!=null&&!['workload','fixed'].includes(s.execution_mode))throw new Unsupported('Unknown execution mode');
    const extra=['session_concurrency','seconds_per_tick','decode_tokens_per_tick'];
    if(Object.keys(e).some(k=>![...keys,...extra].includes(k)))throw new Unsupported('Unsupported execution settings');
    for(const k of keys)if(!integer(e[k],keys.indexOf(k)<4?1:0))fail('Invalid execution setting '+k);
    for(const k of ['session_concurrency','decode_tokens_per_tick'])if(e[k]!=null&&!integer(e[k],1))fail('Invalid '+k);
    if(e.seconds_per_tick!=null&&(!Number.isFinite(e.seconds_per_tick)||e.seconds_per_tick<=0))fail('Invalid seconds_per_tick');
    for(const r of reqs)for(const k of ['wait_seconds','duration_seconds'])if(r[k]!=null&&(!Number.isFinite(r[k])||r[k]<0))fail('Invalid '+k);
    if(checkEvents){if(!Array.isArray(s.events))fail('Invalid event list');if(s.events.length>100000)throw new ResourceLimit('执行事件超过工具单次上限 100,000 条');}
  }
  function generateEvents(reqs,e) {
    const waiting=[...reqs],active=new Map(),releasing=new Map(),decoding=new Map(),done=new Set(),events=[];let tick=0;
    const emit=(kind,id,extra={})=>{if(events.length>=100000)throw new ResourceLimit('执行事件超过工具单次上限 100,000 条');events.push({seq:events.length,tick,kind,request_id:id,...extra});};
    while(waiting.length||active.size||releasing.size||decoding.size){
      if(tick>100000)fail('Event generation did not terminate');
      for(const [id,at] of [...releasing])if(at<=tick){emit('P_RELEASE',id);releasing.delete(id);decoding.set(id,tick+e.decode_ticks);}
      for(const [id,at] of [...decoding])if(at<=tick){emit('REQUEST_COMPLETE',id);done.add(id);decoding.delete(id);}
      for(const r of [...waiting]){const occupied=active.size+releasing.size+decoding.size,pactive=[...active.values()].filter(x=>x[0].p_domain===r.p_domain).length;
        if(occupied>=e.concurrency||pactive>=e.p_slots||['send_after','context_after'].some(k=>r[k]&&!done.has(r[k])))continue;
        emit('ARRIVE',r.id);active.set(r.id,[r,0]);waiting.splice(waiting.indexOf(r),1);
      }
      const budgets=new Map();
      for(const [id,[r,pos]] of [...active]){const p=r.p_domain,budget=budgets.get(p)??e.step_budget;if(budget<=0)continue;const delta=Math.min(e.chunk_tokens,budget,inputLength(r)-pos),target=pos+delta;emit('SCHEDULE',id,{target,budget:delta});emit('STEP_COMPLETE',id,{target});budgets.set(p,budget-delta);active.get(id)[1]=target;if(target===inputLength(r)){active.delete(id);releasing.set(id,tick+e.transfer_ticks);}}
      if(waiting.length&&!active.size&&!releasing.size&&!decoding.size)fail('Dependency cycle or unsatisfied dependency');tick++;
    }
    return events;
  }
  function compileScenario(settings={},builtinPlan=null) {
    settings=clone(settings);
    if(settings.schema===WORKLOAD_SCHEMA)settings={workload:'replay_workload',data:settings};
    if(settings.tasks||settings.plan_kind||settings.schema)throw new Unsupported("Use a supported workload import, not a raw Replay plan or unknown schema");
    if(settings.schema_version===1){validate(settings);return settings;}
    if(settings.schema_version!=null)throw new Unsupported('Unsupported scenario version');
    const allowed=['config','p_domains','workload','synthetic','requests','routing','routing_mode','execution','execution_mode','events','data','plan','captures'];
    if(Object.keys(settings).some(k=>!allowed.includes(k)))throw new Unsupported('Unknown settings format; use workload or scenario import');
    const config=settings.config??{};resolve(config);
    let assumptions=['Virtual ticks specify ordering, not seconds or device speed.','A scheduling step commits before the next step; pending state is never reused.','D outputs are content only; no D→P KV return.'];
    const source=settings.workload??'synthetic';let reqs;
    if(source==='replay_workload'){validateWorkload(settings.data);reqs=settings.data.requests.map(r=>({id:r.runtime_request_id,session:r.runtime_session_id,actor_id:r.actor_id,actor_role:r.actor_role,node_type:r.node_type,source_key:r.source_key,...(r.node_type==='request'?{tokens:r.tokens}:{parts:[]}),output_tokens:r.output_tokens??0,send_after:r.send_after,context_after:r.context_after,context_mode:r.context_mode,cache_identity:r.cache_identity??'',source_kind:r.content_source??'timing',wait_seconds:r.effective_interval_seconds,duration_seconds:r.effective_duration_seconds??0}));assumptions.push(...settings.data.metadata.assumptions);}
    else if(source==='replay425'||source==='agentinfer'){let notes;[reqs,notes]=agentinfer(source==='replay425'?builtinPlan:settings.plan,settings.captures);assumptions.push(...notes);}
    else if(source==='custom')reqs=settings.requests;
    else if(source==='synthetic')reqs=synthetic(settings.synthetic);
    else fail('Unknown workload');
    const domains=settings.p_domains??4;if(!integer(domains,1)||domains>16)fail('p_domains must be in 1..16');
    const sessions=[...new Set(reqs.map(r=>r.session))],mapping=settings.routing??{};
    for(const r of reqs){if(!r.tokens)r.parts=canonical(r.parts);r.p_domain??=mapping[r.session]??(settings.routing_mode==='p0'?0:sessions.indexOf(r.session)%domains);r.send_after??=null;r.context_after??=null;r.source_kind??='explicit_segments';}
    const execution={concurrency:3,p_slots:2,chunk_tokens:8192,step_budget:8192,transfer_ticks:1,decode_ticks:2,...(source==='replay_workload'?settings.data.metadata.execution_defaults:{}),...settings.execution};
    const s={schema_version:1,config,p_domains:domains,requests:reqs,execution,assumptions,workload:source};if(source==='replay_workload'){s.workload_metadata=clone(settings.data.metadata);s.sessions=clone(settings.data.metadata.sessions);s.execution_mode=settings.execution_mode??'workload';s.execution.session_concurrency??=settings.data.metadata.session_concurrency;}
    else if(settings.execution_mode)s.execution_mode=settings.execution_mode;
    validate(s,false);
    if(s.execution_mode==='workload'){s.events=[];s.assumptions.push('Workload-driven virtual scheduling; seconds are normalized by seconds_per_tick (default 1); decode uses decode_ticks + ceil(output_tokens/decode_tokens_per_tick), default 256. No measured throughput.');}
    else {if(source==='replay_workload'&&!settings.events?.length)throw new Unsupported('Replay workload 请使用负载驱动模式；固定回放需要明确的事件流');s.events=settings.events?.length?settings.events:generateEvents(reqs,execution);}
    validate(s);return s;
  }
  class Pool {
    // The upstream queue is represented as: released hashless pages,
    // a lazy interval of never-used IDs, then cached free pages.
    constructor(total){this.total=total;this.pages=new Map();this.emptyFree=new Map();this.free=new Map();this.index=new Map();this.removed=new Map();this.replacements=0;this.empty_reuses=0;this.next_id=1;}
    available(){return Math.max(0,this.total-this.next_id)+this.emptyFree.size+this.free.size;}
    lookup(key){const entries=this.index.get(key);return entries?.size?this.pages.get(entries.keys().next().value):null;}
    touch(page){if(page.refs===0){this.emptyFree.delete(page.id);this.free.delete(page.id);}page.refs++;}
    allocate(seq){
      let p;
      if(this.emptyFree.size){const id=this.emptyFree.keys().next().value;this.emptyFree.delete(id);p=this.pages.get(id);this.empty_reuses++;}
      else if(this.next_id<this.total){p={id:this.next_id++,refs:0,key:null,formed:null,released:null};this.pages.set(p.id,p);}
      else if(this.free.size){const id=this.free.keys().next().value;this.free.delete(id);p=this.pages.get(id);}
      else throw new Infeasible('active_capacity: no reclaimable physical page');
      if(p.key!==null){this.index.get(p.key).delete(p.id);if(!this.index.get(p.key).size)this.index.delete(p.key);this.removed.set(p.key,{formed:p.formed,released:p.released,replaced:seq});this.replacements++;}
      p.key=p.formed=p.released=null;p.refs=1;return p;
    }
    publish(page,key,seq){if(page.key===null){page.key=key;page.formed=seq;if(!this.index.has(key))this.index.set(key,new Map());this.index.get(key).set(page.id,null);}}
    release(page,seq){this.releaseMany([page],seq);}
    releaseMany(pages,seq){
      const empty=[];
      for(const page of pages){if(page.refs<=0)fail('Release without an active reference');if(--page.refs===0){page.released=seq;if(page.key===null)empty.push([page.id,null]);else this.free.set(page.id,null);}}
      if(empty.length)this.emptyFree=new Map([...empty,...this.emptyFree]);
    }
    snapshot(){let active=0,cached=0;for(const p of this.pages.values()){if(p.refs>0)active++;else if(p.key!==null)cached++;}const empty=this.total-1-active-cached;if(empty<0)fail('Physical capacity accounting failed');return {active,cached,empty,reserved:1,replacements:this.replacements,new_allocations:this.next_id-1,empty_reuses:this.empty_reuses,unused:Math.max(0,this.total-this.next_id),released_empty:this.emptyFree.size};}
  }
  function summarize(rows){const done=rows.filter(r=>r.status==='complete'),p=done.reduce((s,r)=>s+r.p_input_tokens,0),h=done.reduce((s,r)=>s+r.adopted_cached_tokens,0),c=done.reduce((s,r)=>s+r.input_compute_tokens,0);return {planned:rows.length,completed:done.length,p_input_tokens:p,adopted_cached_tokens:h,input_compute_tokens:c,input_cache_fraction:p?h/p:null};}
  function commonProcessedPrefix(a,b,limit){
    if((a.cache_identity??'')!==(b.cache_identity??''))return 0;
    if(a.tokens&&b.tokens){let i=0;while(i<limit&&a.tokens[i]===b.tokens[i])i++;return i;}
    if(a.tokens||b.tokens)return null; // Symbolic segments do not establish actual-token identity.
    let i=0,j=0,x=0,y=0,n=0;
    while(n<limit&&i<a.parts.length&&j<b.parts.length){const p=a.parts[i],q=b.parts[j];if(p.id!==q.id||p.start+x!==q.start+y)break;const take=Math.min(p.length-x,q.length-y,limit-n);n+=take;x+=take;y+=take;if(x===p.length){i++;x=0;}if(y===q.length){j++;y=0;}}
    return n;
  }
  function simulate(scenario) {
    validate(scenario);const profile=resolve(scenario.config),groups=profile.groups,A=profile.alignment,pools=range(0,scenario.p_domains).map(()=>new Pool(profile.num_blocks)),states=new Map(scenario.requests.map(row=>[row.id,{row,phase:'waiting',position:0,pages:new Map(groups.map(g=>[g.name,new Map()])),pending:null,scheduled_target:null,adopted:0,compute:0,candidate:0,lookup:[],steps:[]}])),keys=new Map(),timeline=[];
    const tokenPrefixCache=new WeakMap(),opportunities={};
    let status='complete',failure=null,lastTick=-1,budgets=new Map();const started=Date.now();
    function key(s,g,i){const end=(i+1)*g.block,slot=JSON.stringify([s.row.id,end]);if(!keys.has(slot))keys.set(slot,s.row.tokens?tokenPrefixKey(s.row,end,tokenPrefixCache):prefixKey(s.row,end));return g.name+':'+keys.get(slot);}
    function required(g,target,start){const b=g.block;return g.kind==='dense'?range(0,ceil(floor(target/g.ratio)/(b/g.ratio))):range(floor(Math.max(0,start-g.window+1)/b),ceil(target/b));}
    function lookup(s,pool){
      let common=0,unknown=false;
      for(const other of states.values())if(other!==s&&other.row.p_domain===s.row.p_domain&&other.position>0){const value=commonProcessedPrefix(s.row,other.row,Math.min(inputLength(s.row),other.position));if(value===null)unknown=true;else common=Math.max(common,value);}
      opportunities[s.row.id]={processed_content_common_prefix:common,content_aligned_boundary:floor(Math.min(common,inputLength(s.row)-1)/A)*A,mixed_content_identity_unknown:unknown,formed_joint_checkpoint:'not independently tracked; inspect per-group formation/replacement evidence'};
      let candidate=floor((inputLength(s.row)-1)/A)*A;s.candidate=candidate;const details=[];
      while(true){const previous=candidate;
        for(const g of groups){const before=candidate,b=g.block;let missing=null;
          if(g.kind==='dense'){let found=0;for(let i=0;i<floor(candidate/b);i++){const k=key(s,g,i);if(pool.lookup(k)===null){missing=k;break;}found+=b;}candidate=floor(found/A)*A;}
          else {const need=ceil((g.window-1)/b);while(candidate){const end=floor(candidate/b);let absent=null;for(let i=Math.max(0,end-need);i<end;i++){const k=key(s,g,i);if(pool.lookup(k)===null){absent=k;break;}}if(absent===null)break;if(missing===null)missing=absent;candidate=Math.max(0,candidate-A);}}
          if(candidate!==before){const detail={group:g.name,before,after:candidate,reason:'required_state_unavailable'};if(pool.removed.has(missing))detail.last_physical_replacement=pool.removed.get(missing);details.push(detail);}
        }
        if(candidate===previous)break;
      }
      const hits=new Map();for(const g of groups){const end=floor(candidate/g.block),start=g.kind==='dense'?0:Math.max(0,end-ceil((g.window-1)/g.block)),pages=new Map(range(start,end).map(i=>[i,pool.lookup(key(s,g,i))]));hits.set(g.name,pages);
        if(candidate){const selected=[...pages.values()],p=selected.at(-1);details.push({group:g.name,before:candidate,after:candidate,reason:'accepted_at_common_boundary',physical_pages:selected.length,boundary_page:p?{id:p.id,formed:p.formed,released:p.released,refs:p.refs}:null});}}
      s.lookup=details;return [candidate,hits];
    }
    function releaseAll(s,pool,seq){for(const g of groups){const pages=s.pages.get(g.name);pool.releaseMany([...pages.keys()].sort((a,b)=>b-a).map(i=>pages.get(i)),seq);pages.clear();}}
    const executedEvents=[],sessionLaunches=[];
    function* driveWorkload(){
      const e=scenario.execution,rows=scenario.requests;
      const sessions=scenario.sessions??[...new Set(rows.map(r=>r.session))].map((id,i)=>({id,launch_order:i,arrival_seconds:0}));
      const pendingSessions=[...sessions].sort((a,b)=>a.launch_order-b.launch_order),launched=new Map(),finishedSessions=new Set(),completed=new Map(),releaseAt=new Map(),decodeAt=new Map(),timerAt=new Map();
      const ticks=seconds=>Math.ceil(seconds/(e.seconds_per_tick??1));let tick=0,seq=0;
      const event=(kind,id,extra={})=>{if(seq>=100000)resourceLimit('执行事件超过工具单次上限 100,000 条');return {seq:seq++,tick,kind,request_id:id,...extra};};
      while([...states.values()].some(s=>!['complete','cancelled'].includes(s.phase))){
        for(const [id,at] of [...releaseAt])if(at<=tick){yield event('P_RELEASE',id);releaseAt.delete(id);decodeAt.set(id,tick+e.decode_ticks+Math.ceil(states.get(id).row.output_tokens/(e.decode_tokens_per_tick??256)));}
        for(const [id,at] of [...decodeAt])if(at<=tick){yield event('REQUEST_COMPLETE',id);completed.set(id,tick);decodeAt.delete(id);}
        for(const [id,at] of [...timerAt])if(at<=tick){yield event('TIMER_COMPLETE',id);completed.set(id,tick);timerAt.delete(id);}
        for(const [sid] of launched)if(rows.filter(r=>r.session===sid).every(r=>['complete','cancelled'].includes(states.get(r.id).phase)))finishedSessions.add(sid);
        for(const session of [...pendingSessions]){
          if(launched.size-finishedSessions.size>=(e.session_concurrency??scenario.workload_metadata?.session_concurrency??sessions.length))break;
          if(ticks(session.arrival_seconds)>tick)continue;
          launched.set(session.id,tick);sessionLaunches.push({session:session.id,tick});pendingSessions.splice(pendingSessions.indexOf(session),1);
        }
        for(const r of rows){
          const s=states.get(r.id);if(s.phase!=='waiting'||!launched.has(r.session))continue;
          if([r.send_after,r.context_after].some(d=>d&&!completed.has(d)))continue;
          const ready=(r.send_after?completed.get(r.send_after):launched.get(r.session))+ticks(r.wait_seconds??0);
          if(tick<ready)continue;
          if(r.node_type==='timing_dependency'){yield event('TIMER_START',r.id);const duration=ticks(r.duration_seconds);if(duration===0){yield event('TIMER_COMPLETE',r.id);completed.set(r.id,tick);}else timerAt.set(r.id,tick+duration);continue;}
          const occupied=[...states.values()].filter(x=>['arrived','running','transfer','decode'].includes(x.phase)).length;
          const pactive=[...states.values()].filter(x=>['arrived','running'].includes(x.phase)&&x.row.p_domain===r.p_domain).length;
          if(occupied>=e.concurrency||pactive>=e.p_slots)continue;
          yield event('ARRIVE',r.id);
        }
        const spent=new Map();let computed=false;
        for(const r of rows){const s=states.get(r.id);if(!['arrived','running'].includes(s.phase))continue;
          const budget=Math.min(e.chunk_tokens,e.step_budget-(spent.get(r.p_domain)??0));if(budget<=0)continue;
          yield event('SCHEDULE',r.id,{budget,advance_from_hit:true});
          const target=s.pending,previous=s.position;yield event('STEP_COMPLETE',r.id,{target});
          spent.set(r.p_domain,(spent.get(r.p_domain)??0)+target-previous);computed=true;
          if(s.phase==='transfer')releaseAt.set(r.id,tick+Math.max(1,e.transfer_ticks));
        }
        if([...states.values()].every(s=>['complete','cancelled'].includes(s.phase)))break;
        if(computed){tick++;continue;}
        const future=[...releaseAt.values(),...decodeAt.values(),...timerAt.values()];
        if(launched.size-finishedSessions.size<(e.session_concurrency??scenario.workload_metadata?.session_concurrency??sessions.length))for(const s of pendingSessions)future.push(ticks(s.arrival_seconds));
        for(const r of rows)if(states.get(r.id).phase==='waiting'&&launched.has(r.session)&&[r.send_after,r.context_after].every(d=>!d||completed.has(d)))future.push((r.send_after?completed.get(r.send_after):launched.get(r.session))+ticks(r.wait_seconds??0));
        const next=future.filter(t=>t>tick).sort((a,b)=>a-b)[0];
        if(next===undefined)fail('Workload cannot progress: unresolved dependencies or execution slots');
        if(!Number.isSafeInteger(next))fail('Virtual time exceeds exact integer range');tick=next;
      }
    }

    const eventSource=scenario.execution_mode==='workload'?driveWorkload():scenario.events;
    let index=-1;
    for(const incoming of eventSource){
      index++;

      if(index%128===0){if(Date.now()-started>85000)resourceLimit('运行超过工具 85 秒计算上限，请减小场景');if(pools.reduce((n,p)=>n+p.pages.size,0)>500000)resourceLimit('超过工具 500,000 个物理块对象上限，请减小场景');}
      const event={...incoming};executedEvents.push(event);
      try {
        if(event.seq!==index||!integer(event.tick)||event.tick<lastTick)fail('Events require consecutive seq and nondecreasing tick');if(event.tick!==lastTick)budgets=new Map();lastTick=event.tick;
        const s=states.get(event.request_id);if(!s)fail('Unknown event request');const domain=s.row.p_domain,pool=pools[domain],kind=event.kind,n=inputLength(s.row);
        if(kind==='TIMER_START'){if(s.phase!=='waiting'||s.row.node_type!=='timing_dependency')fail('Invalid timer start');s.phase='timing';}
        else if(kind==='TIMER_COMPLETE'){if(s.phase!=='timing')fail('Invalid timer completion');s.phase='complete';}
        else if(kind==='ARRIVE'){
          if(s.phase!=='waiting')fail('Duplicate arrival');for(const dep of [s.row.send_after,s.row.context_after])if(dep&&states.get(dep).phase!=='complete')fail('Arrival before dependency completed');
          if([...states.values()].filter(x=>['arrived','running','transfer','decode'].includes(x.phase)).length>=scenario.execution.concurrency)throw new Infeasible('request_concurrency: fixed arrival exceeds slots');s.phase='arrived';
        } else if(kind==='SCHEDULE'){
          if(!['arrived','running'].includes(s.phase)||s.pending!==null)fail('SCHEDULE requires an arrived/committed request');let target=event.target;
          if(!event.advance_from_hit&&(!integer(target,1)||target>n))fail('Invalid schedule target');if(event.advance_from_hit&&scenario.execution_mode!=='workload')fail('Dynamic scheduling flag in fixed events');if(!integer(event.budget))fail('Invalid schedule budget');s.scheduled_target=target;
          const fresh=s.phase==='arrived';let hit,hits;
          if(fresh){if([...states.values()].filter(x=>x.phase==='running'&&x.row.p_domain===domain).length>=scenario.execution.p_slots)throw new Infeasible('p_slots: fixed trace exceeds P sequence slots');[hit,hits]=lookup(s,pool);}else{hit=s.position;hits=s.pages;}
          if(event.advance_from_hit){target=Math.min(n,hit+event.budget);event.target=target;s.scheduled_target=target;}
          target=Math.max(target,hit);const compute=target-hit,used=budgets.get(domain)??0;
          if(compute>event.budget||compute+used>scenario.execution.step_budget)throw new Infeasible('scheduling_budget: new input compute exceeds fixed opportunity');
          if(!fresh)for(const g of groups)if(g.kind==='window'){const cutoff=floor(Math.max(0,s.position-g.window+1)/g.block),pages=s.pages.get(g.name);const skipped=[...pages.keys()].filter(i=>i<cutoff).sort((a,b)=>b-a);pool.releaseMany(skipped.map(i=>pages.get(i)),index);for(const i of skipped)pages.delete(i);}
          const missing=[];for(const g of groups)for(const i of required(g,target,hit))if(!hits.get(g.name).has(i))missing.push([g.name,i]);
          const pinned=new Set();if(fresh)for(const pages of hits.values())for(const p of pages.values())if(p&&p.refs===0)pinned.add(p.id);
          if(fresh){let admission=pinned.size;for(const g of groups){const b=g.block;let needed,skipped;if(g.kind==='dense'){needed=ceil(floor(n/g.ratio)/(b/g.ratio));skipped=0;}else{const cap=ceil(Math.min(g.window-1+scenario.execution.step_budget,scenario.config.max_input_tokens??Infinity)/b)+1;needed=Math.min(ceil(n/b),cap);skipped=floor(Math.max(0,hit-g.window+1)/b);}admission+=Math.max(0,needed-Math.max(skipped,floor(hit/b)));}if(admission>pool.available())throw new Infeasible(`admission_capacity: full-input gate needs ${admission} pages; ${pool.available()} free`);}
          if(missing.length+pinned.size>pool.available())throw new Infeasible(`active_capacity: need ${missing.length} new + ${pinned.size} cached pages; ${pool.available()} free`);
          if(fresh){for(const pages of hits.values())for(const p of pages.values()){if(!p)fail('Selected recovery state disappeared');pool.touch(p);}s.pages=hits;s.adopted=hit;s.position=hit;s.phase='running';}
          for(const [name,i] of missing)s.pages.get(name).set(i,pool.allocate(index));s.pending=target;s.steps.push({event_seq:index,from_token:s.position,to_token:target,compute_tokens:compute});budgets.set(domain,used+compute);
        } else if(kind==='STEP_COMPLETE'){
          if(s.pending===null||event.target!==s.scheduled_target)fail('STEP_COMPLETE has no matching scheduled step');const target=s.pending;
          for(const g of groups){const b=g.block,need=g.window?ceil((g.window-1)/b):0;for(const [i,p] of s.pages.get(g.name)){if((i+1)*b>target||p.key!==null)continue;if(g.kind==='dense'||i%(A/b)>=A/b-need)pool.publish(p,key(s,g,i),index);}}
          s.compute+=target-s.position;s.position=target;s.pending=null;if(target===n)s.phase='transfer';
        } else if(kind==='P_RELEASE'){
          if(s.phase!=='transfer'||s.pending!==null)fail('P_RELEASE before input completion');releaseAll(s,pool,index);s.phase='decode';
        } else if(kind==='REQUEST_COMPLETE'){
          if(s.phase!=='decode')fail('REQUEST_COMPLETE before P release');s.phase='complete';if(s.compute+s.adopted!==n)fail('Input accounting failed');
        } else if(kind==='CANCEL'){
          if(s.pending!==null||s.phase==='transfer')throw new Unsupported('Cancellation with in-flight compute/transfer is not supported');releaseAll(s,pool,index);s.phase='cancelled';
        } else throw new Unsupported('Unsupported event: '+kind);
        if(['STEP_COMPLETE','P_RELEASE'].includes(kind))timeline.push({event_seq:index,tick:lastTick,p_domain:domain,...pool.snapshot()});
      } catch(error){if(!(error instanceof Infeasible))throw error;status=scenario.execution_mode==='workload'?'infeasible_under_execution_rules':'infeasible_under_fixed_trace';failure={event_seq:index,request_id:event.request_id,reason:error.message};break;}
    }
    if(status==='complete'&&[...states.values()].some(s=>!['complete','cancelled'].includes(s.phase)))fail('Trace ended without completing every request');
    if(status==='complete'&&[...states.values()].some(s=>s.phase==='cancelled'))status='cancelled';
    const rows=[...states].filter(([,s])=>s.row.node_type!=='timing_dependency').map(([id,s])=>({request_id:id,session:s.row.session,p_domain:s.row.p_domain,input_tokens:inputLength(s.row),p_input_tokens:inputLength(s.row),candidate_tokens:s.candidate,adopted_cached_tokens:s.adopted,input_compute_tokens:s.compute,status:s.phase,limiting_groups:[...new Set(s.lookup.filter(x=>x.after<x.before).map(x=>x.group))],explanation:s.lookup,steps:s.steps,source_kind:s.row.source_kind}));
    const perP=pools.map((pool,domain)=>({p_domain:domain,...summarize(rows.filter(r=>r.p_domain===domain)),...pool.snapshot(),active_peak:Math.max(0,...timeline.filter(x=>x.p_domain===domain).map(x=>x.active))}));
    return {simulator_version:'0.3.0',diagnostics:{prefix_opportunities:opportunities,scope:'Same P and isolation; previously processed content, NOT proof of a jointly formed or currently resident checkpoint.'},status,failure,scenario,profile,requests:rows,summary:summarize(rows),per_p:perP,timeline,metric_scope:'Completed requests only; partial results are not complete capacity points.',...(scenario.execution_mode==='workload'?{executed_events:executedEvents,session_launches:sessionLaunches}: {})};
  }
  function run(body,builtinPlan) {
    const scenario=compileScenario(body.scenario??body.settings??{},builtinPlan),points=body.capacities;
    if(points!==undefined&&(!Array.isArray(points)||points.length<1||points.length>8))fail('Use 1..8 capacity points');
    return {results:(points??[null]).map(point=>{const s={...scenario,config:{...scenario.config}};if(point!==null){delete s.config.kv_bytes;s.config.kv_gib=Number(point);}return simulate(s);})};
  }
  return {WORKLOAD_SCHEMA,validateWorkload,inspectImport,Unsupported,Infeasible,ResourceLimit,syntheticSummary,inputLength,canonical,length,prefix,segment,tokenParts,prefixKey,sha256,resolve,synthetic,agentinfer,validate,generateEvents,compileScenario,Pool,simulate,summarize,run};
})();
if(typeof module!=='undefined')module.exports=KVSim;
