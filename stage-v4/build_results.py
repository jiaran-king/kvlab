"""Independent six-session series. Keep failed attempts outside valid-point lines."""
import csv,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
root=Path(__file__).resolve().parent;out=root/'results';out.mkdir(exist_ok=True)
selection=json.loads((root/'run-selection.json').read_text());rows=[];curves=[];gauges=[];stages=[];cohorts=[]
for spec in selection:
 run=Path(spec['run']);p=json.loads((run/'point-summary.json').read_text());event=json.loads((run/'event-summary.json').read_text());obs=json.loads((run/'observation-summary.json').read_text());supp=json.loads((root/(spec['label']+'-supplement.json')).read_text());execution=json.loads((run/'replay/replay-execution.json').read_text())['summary']
 prefill=[s for s in supp['stage_means'] if s['role']=='P' and s['metric']=='vllm:request_prefill_time_seconds']
 row=dict(label=spec['label'],job=spec['job'],p_kv_gib=p['p_kv_budget_bytes_per_card']/2**30,planned=p['planned'],success=p['success'],failed=p['failed'],dependency_skipped=execution['dependency_skipped_requests'],not_recorded=p['not_recorded'],p_blocks=p['p_num_gpu_blocks'],hit_tokens=p['p_hit_tokens'],query_tokens=p['p_query_tokens'],hit_rate=p['p_local_hit_fraction'],local_compute=p['p_local_compute_tokens'],local_cache_hit=p['p_local_cache_hit_tokens'],p_external_tokens=p['p_external_tokens'],d_local_compute=p['d_local_compute_tokens'],d_external_tokens=p['d_external_tokens'],local_compute_input_fraction=p['p_local_compute_tokens']/(p['p_local_compute_tokens']+p['p_local_cache_hit_tokens']+p['p_external_tokens']),removed_entries=event['total_removed_entries'],removal_groups=json.dumps(event['groups']),event_complete=event['stream_complete'],formal_clears=event['extra_formal_clears'],p_prefill_mean_seconds=prefill[0]['mean_seconds'] if prefill else None,continuation_n=p['continuation_ttft_n'],ttft_p50=p['continuation_ttft_p50_seconds'],ttft_p95=p['continuation_ttft_p95_seconds'],e2e_p50=supp['e2e_p50_seconds'],e2e_p95=supp['e2e_p95_seconds'],task_window_seconds=p['replay_task_window_seconds'],p_preemptions=p['p_preemptions'],d_preemptions=p['d_preemptions'],max_inflight=obs['http_peak_inflight'],six_sessions_overlap=obs['all_six_started_before_any_session_finished'],run=str(run))
 row['series']=spec['series']
 row['admitted_requests']=obs['request_admissions']
 row['admitted_without_outcome']=obs['request_admissions']-p['success']-p['failed']
 row['not_admitted']=p['planned']-obs['request_admissions']
 row['failed_sessions']=execution['failed_tasks']
 row['p_prefill_count']=prefill[0]['delta_count'] if prefill else None
 row['valid_comparison']=p['success']==p['planned'] and not p['failed'] and not p['not_recorded'] and event['stream_complete'] and not event['extra_formal_clears'] and obs['all_six_started_before_any_session_finished'] and obs['http_peak_inflight']<=3
 rows.append(row)
 for g in obs['gauges']:gauges.append(dict(label=spec['label'],series=spec['series'],**g))
 for g in supp['stage_means']:stages.append(dict(series=spec['series'],**g))
 for name,g in obs['ttft_cohorts'].items():cohorts.append(dict(label=spec['label'],series=spec['series'],cohort=name,**g))
 curves.append((row,list(csv.DictReader((run/'removal-progress.csv').open()))))
with (root/'summary.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
for name,data in [('auxiliary-gauges.csv',gauges),('auxiliary-stage-means.csv',stages),('ttft-cohorts.csv',cohorts)]:
 with (root/name).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
for key,name,ylabel in [('hit_rate','capacity-hit-rate.png','Local hit rate (%)'),('local_compute','capacity-local-compute.png','Local compute input tokens (millions)'),('ttft','capacity-ttft.png','Continuation TTFT (seconds)')]:
 fig,axes=plt.subplots(1,2,figsize=(10,4.5),gridspec_kw={'width_ratios':[2,1]})
 fig.subplots_adjust(left=.08,right=.98,bottom=.17,top=.80,wspace=.34)
 for ax,main,title in zip(axes,[True,False],['Main: fixed 425 requests','Historical L: 425/467 success']):
  selected=[r for r in rows if (r['series']=='successful-425')==main]
  for r in selected:
   suffix=('' if r['valid_comparison'] else ' incomplete') if main else ' partial'
   if key=='ttft':
    for stat,color,marker in [('p50','#2276b5','o'),('p95','#d97924','^')]:
     v=r['ttft_'+stat]
     if v is None:continue
     ax.scatter(r['p_kv_gib'],v,c=color,marker=marker);ax.annotate(r['label']+suffix+' '+stat+' %.3f'%v,(r['p_kv_gib'],v),xytext=(0,8),textcoords='offset points',ha='center',fontsize=8)
   else:
    v=r[key]*(100 if key=='hit_rate' else 1e-6);ax.scatter(r['p_kv_gib'],v,c='#2276b5' if main else '#a33b32',marker='o' if main else 'x');ax.annotate(r['label']+suffix+' %.2f'%v,(r['p_kv_gib'],v),xytext=(0,8),textcoords='offset points',ha='center',fontsize=8)
  ax.set(xlabel='P KV per GPU (GiB)',ylabel=ylabel,xticks=sorted({r['p_kv_gib'] for r in selected}) if main else [12],xlim=(min([r['p_kv_gib'] for r in selected] or [12])-8,56) if main else (8,16),title=title)
  top=max(([r['ttft_p95'] for r in selected] if key=='ttft' else [r[key]*(100 if key=='hit_rate' else 1e-6) for r in selected]) or [1])
  ax.set_ylim(0,100 if key=='hit_rate' else top*1.22);ax.set_title(title,fontsize=11);ax.grid(axis='y',alpha=.2)
 fig.suptitle('Separate workload scopes; single runs; see panel scales',fontsize=12);fig.savefig(out/name,dpi=180,bbox_inches='tight');plt.close(fig)
def group_key(g):return tuple('' if g.get(k) is None else str(g[k]) for k in ['engine','medium','group_idx','locality'])
all_groups=sorted({group_key(g) for r,_ in curves for g in json.loads(r['removal_groups'])})
import math
fig,axes=plt.subplots(math.ceil(max(1,len(all_groups))/2),2,figsize=(12,3*math.ceil(max(1,len(all_groups))/2)),layout='constrained',squeeze=False)
for ax,group in zip(axes.flat,all_groups):
 for r,curve in curves:
  cs=[c for c in curve if tuple(c[k] for k in ['engine','medium','group_idx','locality'])==group]
  if cs or (r['event_complete'] and group in {group_key(g) for g in json.loads(r['removal_groups'])}):
   xs=[0]+[int(c['completed_requests']) for c in cs]+[r['success']+r['failed']]
   ys=[0]+[int(c['cumulative_removed_in_group']) for c in cs]
   ys.append(ys[-1])
   ax.step(xs,ys,where='post',linestyle='--' if not r['valid_comparison'] else '-',label=r['label']+(' historical 467 (partial)' if r['series']!='successful-425' else ' 425 requests'+(' incomplete' if not r['valid_comparison'] else '')))
 ax.set(xlabel='Completed requests (alignment only)',ylabel='Removed hash entries',title='Group '+group[2]+' / '+group[1]);ax.legend(fontsize=8);ax.grid(alpha=.2)
for ax in list(axes.flat)[len(all_groups):]:ax.set_visible(False)
fig.suptitle('Cache removals — mixed causes; group y-scales differ');fig.savefig(out/'removal-progress.png',dpi=180,bbox_inches='tight');plt.close(fig)
print('Wrote',len(rows),'runs and four figures')
