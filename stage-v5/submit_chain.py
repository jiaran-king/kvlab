"""Single bounded submission: three afterok jobs, no restart or polling loop."""
import fcntl,json,os,subprocess,time
from pathlib import Path
here=Path(__file__).resolve().parent
with (here/'submission.lock').open('w') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 ledger=here/'submitted.json'
 if ledger.exists():raise RuntimeError('Pipeline already submitted; inspect submitted.json, do not resubmit')
 rows=[];previous=None;capture=None
 try:
  for label,budget in [('C12',12),('F12',12),('F24',24)]:
   export=f'ALL,CAPACITY_LABEL={label},P_KV_BYTES={budget*1024**3},D_KV_BYTES={48*1024**3}'
   cmd=['sbatch','--parsable',f'--job-name=v5-{label}',f'--export={export}','--kill-on-invalid-dep=yes']
   if previous:
    cmd[3]+=f',PREVIOUS_RUN={here}/formal-{previous},FROZEN_RUN={here}/formal-{capture}'
    cmd.append(f'--dependency=afterok:{previous}')
   cmd.append(str(here/'pd_formal.slurm'))
   output=subprocess.check_output(cmd,universal_newlines=True,timeout=30).strip();job=output.split(';')[0];assert job.isdigit()
   rows.append({'label':label,'job_id':job,'run':str(here/f'formal-{job}'),'submitted_at':time.time(),'command':cmd})
   ledger.write_text(json.dumps({'jobs':rows,'complete':False},indent=2))
   if capture is None:capture=job
   previous=job
  terminal=subprocess.check_output(['sbatch','--parsable',f'--dependency=afterany:{previous}',str(here/'collect_terminal.slurm')],universal_newlines=True,timeout=30).strip().split(';')[0]
  assert terminal.isdigit()
  ledger.write_text(json.dumps({'jobs':rows,'terminal_job':terminal,'complete':True},indent=2))
 except BaseException:
  # Cancel only the exact jobs created by this failed submission pass.
  for row in rows:subprocess.run(['scancel',row['job_id']],timeout=20)
  raise
 print(ledger.read_text())
