"""Recompute paired input and lookup evidence from bounded CPU summaries."""
import csv,json,collections
from pathlib import Path
b=Path(__file__).parent/'cpu-3468'
rows={x:{r['source_key']:r for r in csv.DictReader((b/f'{x}-requests.csv').open())} for x in ['F12','F24']}
p=list(csv.DictReader((b/'paired-requests.csv').open()));stats=collections.Counter();examples=[]
for r in p:
 delta=int(r['delta_A']);stats['net_adopted_gain']+=delta;stats['positive' if delta>0 else 'negative' if delta<0 else 'zero']+=1
 if delta<=0:continue
 a,z=[rows[x][r['source_key']] for x in ['F12','F24']]
 ga,gz=[json.loads(v['lookup_call_sequence']) for v in [a,z]]
 stats['positive_full_predecessor']+=int(a['lcp_tokens'])==int(a['predecessor_input_tokens'])
 clean=all(g['candidate']==g['returned'] for g in ga[1:]+gz[1:])
 if clean and gz[0]['returned']-ga[0]['returned']==delta:stats['group0_only_return_difference']+=1
 else:examples.append(dict(source_key=r['source_key'],delta_A=delta,F12=ga,F24=gz))
result={'counts':dict(stats),'additional_group_contraction_examples':examples}
(b/'mechanism-summary.json').write_text(json.dumps(result,indent=2));print(json.dumps(stats,indent=2))
