import json
import sys
from pathlib import Path
from kvsim.inputs import compile_scenario
from kvsim.engine import simulate
cases=[]
for block in (32,64,128):
 for capacity in (.01,1,8,24):
  settings={'config':{'block_size':block,'kv_gib':capacity},'synthetic':{'chains':2,'rounds':3,'competitors':2},'p_domains':2}
  s=compile_scenario(settings);cases.append({'settings':settings,'scenario':s,'result':simulate(s)})
for limit in (None, 131072):
 settings={'config':{'kv_gib':64,'block_size':128,'max_input_tokens':limit},'p_domains':1,'synthetic':{'chains':1,'rounds':2,'first_tokens':100000,'increment':4096,'output_tokens':256}}
 s=compile_scenario(settings);cases.append({'settings':settings,'scenario':s,'result':simulate(s)})
for name in ('default','replay425'):
 settings=json.loads(Path('kvsim/cases/'+name+'.json').read_text());s=compile_scenario(settings);cases.append({'settings':settings,'scenario':s,'result':simulate(s)})
Path(sys.argv[1]).write_text(json.dumps(cases))
