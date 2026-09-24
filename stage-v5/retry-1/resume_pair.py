import fcntl,json,subprocess,time
from pathlib import Path
p=Path(__file__).resolve().parent
with (p/'submission.lock').open('w') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 out=p/'resumed-1.json';assert not out.exists(),'Already resumed'
 old=json.loads((p/'submitted.json').read_text());capture=old['jobs'][0];c=Path(capture['run'])
 assert json.loads((c/'ACCEPTED.json').read_text())['passed']
 assert json.loads((c/'cleanup-audit.json').read_text())['resource_cleanup_passed']
 rows=[capture];created=[];prev=None
 try:
  for label,budget in [('F12',12),('F24',24)]:
   previous=c if prev is None else p/f'formal-{prev}'
   export=f'ALL,CAPACITY_LABEL={label},P_KV_BYTES={budget*1024**3},D_KV_BYTES={48*1024**3},PREVIOUS_RUN={previous},FROZEN_RUN={c}'
   cmd=['sbatch','--parsable',f'--job-name=v5-{label}','--kill-on-invalid-dep=yes',f'--export={export}']
   if prev:cmd.append(f'--dependency=afterok:{prev}')
   cmd.append(str(p/'pd_formal.slurm'))
   job=subprocess.check_output(cmd,universal_newlines=True,timeout=30).strip().split(';')[0];assert job.isdigit();created.append(job)
   rows.append({'label':label,'job_id':job,'run':str(p/f'formal-{job}'),'submitted_at':time.time(),'command':cmd});prev=job
   out.write_text(json.dumps({'jobs':rows,'complete':False},indent=2))
  terminal=subprocess.check_output(['sbatch','--parsable',f'--dependency=afterany:{prev}',f'--export=ALL,SUBMISSION_MANIFEST={out}',str(p/'collect_terminal.slurm')],universal_newlines=True,timeout=30).strip().split(';')[0]
  out.write_text(json.dumps({'jobs':rows,'terminal_job':terminal,'complete':True},indent=2))
 except BaseException:
  for job in created:subprocess.run(['scancel',job],timeout=20)
  raise
 print(out.read_text())
