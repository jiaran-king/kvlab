"""Summarize sampled residency histograms by exact series labels, without quantile claims."""
import json,re,sys
from pathlib import Path
run=Path(sys.argv[1])
def read(phase):
 result={}
 for line in (run/f'formal-{phase}-P.prom').read_text().splitlines():
  m=re.fullmatch(r'(vllm:kv_block_\w+_(?:sum|count|bucket))\{([^}]*)\} ([\d.e+-]+)',line)
  if m:result[(m[1],m[2])]=float(m[3])
 return result
before,after=read('before'),read('after');rows=[]
for (name,labels),value in after.items():
 initial=before.get((name,labels));change=None if initial is None else value-initial
 rows.append({'metric':name,'labels':labels,'before':initial,'after':value,'delta':change})
result={'sampling':0.01,'available':bool(rows),'series':rows,'limitation':'Marginal sampled histograms cannot establish per-block eviction before its next reuse; absent initial series is missing, not assumed zero.'}
(run/'residency-summary.json').write_text(json.dumps(result,indent=2));print('residency series',len(rows))
