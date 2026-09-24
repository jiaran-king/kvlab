"""Validate request admission and summarize existing gauges without mixing counters."""
import collections,csv,json,re,sys
from pathlib import Path
from summarize_point import percentile
run=Path(sys.argv[1]);rows=[json.loads(l) for l in (run/'request-admission.jsonl').read_text().splitlines()]
chron=sorted([(r['acquired_monotonic'],1,r['session_id']) for r in rows]+[(r['finished_monotonic'],-1,r['session_id']) for r in rows])
active=0;peak=0
for _,delta,_ in chron:active+=delta;peak=max(peak,active)
assert peak<=3 and active==0
sessions=collections.defaultdict(list)
for r in rows:sessions[r['session_id']].append(r)
intervals={s:[min(r['acquired_monotonic'] for r in rs),max(r['finished_monotonic'] for r in rs)] for s,rs in sessions.items()}
all_started_before_first_finished=max(v[0] for v in intervals.values())<min(v[1] for v in intervals.values())
start=min(r['acquired_time'] for r in rows);end=max(r['finished_time'] for r in rows)
metrics=collections.defaultdict(list);scrape_errors=[];scrape_times=collections.defaultdict(list)
for line in (run/'metrics-samples.jsonl').open():
 r=json.loads(line)
 if not start<=r['time']<=end:continue
 if 'error' in r:scrape_errors.append(r);continue
 scrape_times[r['role']].append(r['time'])
 for l in r['text'].splitlines():
  m=re.fullmatch(r'(vllm:(?:kv_cache_usage_perc|num_requests_running|num_requests_waiting))\{([^}]*)\} ([\d.e+-]+)',l)
  if m:metrics[(r['role'],m[1],m[2])].append(float(m[3]))
gauges=[{'role':k[0],'metric':k[1],'labels':k[2],'samples':len(v),'sample_mean':sum(v)/len(v),'sample_peak':max(v)} for k,v in metrics.items()]
cohorts=collections.defaultdict(list)
for name in ['first_actor_request','independent','reset','continuation']:cohorts[name]=[]
for r in csv.DictReader((run/'requests-enriched.csv').open()):
 cohort='reset' if r['calibration_adjustment'] in ('reset','reset_and_pad') or r['context_mode']=='reset' else 'continuation' if r['cohort']=='continuation' else 'first_actor_request' if r['actor_turn']=='1' else 'independent'
 if r['http_status']=='success' and r['ttft_seconds']:cohorts[cohort].append(float(r['ttft_seconds']))
result={'request_admissions':len(rows),'http_peak_inflight':peak,'session_intervals':intervals,'all_six_started_before_any_session_finished':len(sessions)==6 and all_started_before_first_finished,'admission_wait_mean':sum(r['admission_wait_seconds'] for r in rows)/len(rows),'admission_wait_p95':percentile([r['admission_wait_seconds'] for r in rows],.95),'gauges':gauges,'metrics_scrape_errors':scrape_errors,'scrape_max_gap_seconds':{k:max([b-a for a,b in zip(v,v[1:])] or [0]) for k,v in scrape_times.items()},'ttft_cohorts':{k:{'n':len(v),'p50':percentile(v,.5),'p95':percentile(v,.95)} for k,v in cohorts.items()},'timing_note':'HTTP TTFT excludes admission wait; original executor send offset is before admission, so admission log is authoritative for actual HTTP concurrency.'}
(run/'observation-summary.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
