#!/bin/bash
#SBATCH --job-name=v5-terminal
#SBATCH --partition=h20
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:03:00
#SBATCH --no-requeue
#SBATCH --output=/home/david_cwq/zhouziheng/agent-replay-20260917/evidence/pd-capacity-20260919/stage-v5/retry-1/terminal-%j.out
set -euo pipefail
D=/home/david_cwq/zhouziheng/agent-replay-20260917/evidence/pd-capacity-20260919/stage-v5/retry-1
python3 - "$D" <<'PY'
import json,subprocess,sys,time,os
from pathlib import Path
p=Path(sys.argv[1]);manifest=Path(os.environ.get('SUBMISSION_MANIFEST',str(p/'submitted.json')));data=json.loads(manifest.read_text());states=[]
for row in data['jobs']:
 j=row['job_id'];s=subprocess.run(['scontrol','show','job',j],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,universal_newlines=True,timeout=15)
 a=subprocess.run(['sacct','-j',j,'--format=JobID,State,ExitCode,Elapsed,Start,End','--parsable2'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,universal_newlines=True,timeout=15)
 states.append(dict(job_id=j,label=row['label'],scontrol=s.stdout,sacct=a.stdout))
 run=Path(row['run'])
 if run.exists():(run/'scheduler-final.txt').write_text(s.stdout+'\n'+a.stdout)
(p/('scheduler-terminal-'+manifest.stem+'.json')).write_text(json.dumps({'time':time.time(),'states':states},indent=2))
PY
