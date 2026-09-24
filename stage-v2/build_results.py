"""Combine existing per-run statistics; never pool requests across runs."""
import csv,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root=Path(__file__).resolve().parent
specs=json.loads((root/'run-selection.json').read_text())
out=root/'results';out.mkdir(exist_ok=True)
points=[];stages=[]
for spec in specs:
 run=Path(spec['run'])
 point=json.loads((run/'point-summary.json').read_text())
 supplement=json.loads((root/(point['label']+'-supplement.json')).read_text())
 point.update(spec)
 execution=json.loads((run/'replay/replay-execution.json').read_text())['summary']
 outcomes=[json.loads(line) for line in (run/'replay/requests.jsonl').read_text().splitlines()]
 for key in ['attempted_requests','successful_requests','failed_requests','pre_send_failed_requests','dependency_skipped_requests','planned_tasks','completed_tasks','failed_tasks']:
  point['execution_'+key]=execution.get(key)
 point['client_timeout_requests']=sum('timeout' in (r.get('error') or '').lower() for r in outcomes)
 point['client_recorded_requests']=len(outcomes)
 point['client_unrecorded_planned_requests']=point['planned']-len(outcomes)
 point['latency_sample_scope']='successful requests only; incomplete run' if point['success']!=point['planned'] else 'all planned requests succeeded'
 point['p_kv_gib_per_card']=point['p_kv_budget_bytes_per_card']/2**30
 for k in ['e2e_sample_count','e2e_p50_seconds','e2e_p95_seconds','formal_manifest_duration_seconds']:
  point[k]=supplement[k]
 for role in ['P','D']:
  for k,v in supplement['log_observations'][role].items():
   if k!='events':point[role.lower()+'_'+k]=v
 stages.extend(supplement['stage_means']);points.append(point)
for name,rows in [('summary.csv',points),('stage-means.csv',stages)]:
 with (out/name).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
for metric,filename,title in [('hit','capacity-hit-rate.png','P local prefix reuse'),('ttft','capacity-ttft.png','Continuation TTFT')]:
 fig,axes=plt.subplots(1,2,figsize=(10,4.6),gridspec_kw={'width_ratios':[2,1]},layout='constrained')
 for ax,group,subtitle in zip(axes,['main','historical'],['Main comparison: single runs','Historical H: compile activity']):
  rows=sorted([p for p in points if p['comparison_group']==group],key=lambda p:p['p_kv_gib_per_card'])
  for p in rows:
   if p['success']!=p['planned'] or p['failed'] or p['not_recorded']:
    ax.annotate(p['label']+': incomplete',(p['p_kv_gib_per_card'],0));continue
   x=p['p_kv_gib_per_card']
   if metric=='hit':
    y=100*p['p_local_hit_fraction'];ax.scatter([x],[y],color='#2276b5',s=65)
    ax.annotate(f"{p['label']}  {y:.2f}%",(x,y),xytext=(0,10),textcoords='offset points',ha='center')
   else:
    for stat,marker,color,offset in [('p50','o','#2276b5',-16),('p95','^','#d97924',10)]:
     y=p[f'continuation_ttft_{stat}_seconds'];ax.scatter([x],[y],color=color,marker=marker,s=60)
     ax.annotate(f"{p['label']} {stat.upper()} {y:.3f}",(x,y),xytext=(0,10 if group=='historical' else offset),textcoords='offset points',ha='center',fontsize=8)
  ax.set_title(subtitle);ax.set_xlabel('P KV budget per GPU (GiB)');ax.set_xticks([12,24,48]);ax.set_xlim(6,57)
  ax.grid(axis='y',alpha=.2)
  if group=='main':
   for p in points:
    if p['comparison_group']=='failed':
     x=p['p_kv_gib_per_card'];ax.axvline(x,color='#a33b32',linestyle=':',alpha=.6)
     ax.text(x,.48,f"{p['label']}: incomplete\n{p['success']}/{p['planned']} succeeded\nnot a comparable point",transform=ax.get_xaxis_transform(),ha='center',va='center',fontsize=9,color='#a33b32',bbox={'facecolor':'white','edgecolor':'none','alpha':.9})
  if metric=='hit':ax.set_ylim(0,105);ax.set_ylabel('Token-weighted local hit rate (%)')
  else:
   max_y=max([p['continuation_ttft_p95_seconds'] or 0 for p in rows]+[1]);ax.set_ylim(0,max_y*1.27);ax.set_ylabel('Seconds (panel scales differ)')
 fig.suptitle(title+' — all runs retained; no fitted curve')
 fig.savefig(out/filename,dpi=180);plt.close(fig)
print('Wrote',len(points),'individual runs to',out)
