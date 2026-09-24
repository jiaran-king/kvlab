# Execution state — 2026-09-19

Read GOAL.md for the full unchanged objective. Formal replays started: **0 / 4**. No model server has been started yet. Goal remains active.

## Authoritative locations

- Remote workspace: `/home/david_cwq/zhouziheng/agent-replay-20260917` (ROOT below).
- This experiment: `ROOT/evidence/pd-capacity-20260919` (RUNROOT).
- Model: `/home/david_cwq/jinghaoyu/models/DeepSeek-V4-Flash`.
- Runtime: `ROOT/runtime` vLLM 0.26.0; client `ROOT/client`.
- AgentInfer checkout: `ROOT/src/agent-infer`, HEAD exactly `7f304555a8bc504c2c2257db2662e896eeeb5c30`, with four pre-existing modified replay files. Preserve and record diff; do not overwrite.

## Completed progress

- Copied goal into local GOAL.md.
- Extracted exact three full sessions from git-show of pinned source into local `evidence/selected-trace.jsonl` and remote RUNROOT/selected-trace.jsonl. Counts 65+75+34=174; max input+output 75768. Source has 597 records.
- Head originally under memory pressure (31 MiB available) due to hundreds of exact `codex --version` probes. One authorized bounded cleanup killed 522 precisely attributed probes, all gone immediately; available memory recovered to ~3 GiB. Attribution saved remote RUNROOT/known-probe-cleanup.json and local evidence. Do not repeat dedicated cleanup loop; reconnect exception applies.
- SLURM initially empty; both nodes idle. Job 3332: four-GPU preflight on node01, COMPLETED 0:0, 15 sec. Devices H20-3e SM90 each 150110011392 bytes (~139.8 GiB). Compute available RAM ~2.1 TB. Health gate passed (only known root amperf dmesg zombie excluded by existing exact attribution).
- 3332 GPU apps before/after empty; IPC and listening ports identical; shared-memory diff only existing root monitoring files/timestamps, no task-created residue. Remote scheduler-final.txt confirms terminal state. Evidence downloaded local evidence/preflight-3332.
- Downloaded official v0.26.0 Mooncake proxy to scripts/mooncake_connector_proxy.py; copied to RUNROOT. Upstream shell example saved evidence/upstream-mooncake.sh for reference ONLY: it contains broad pkill and MUST NOT be executed.
- Runtime MooncakeConnector handles hybrid cache groups. Runtime initially lacks mooncake and nixl.
- Job 3333 installed mooncake-transfer-engine 0.3.13.post1 into RUNROOT/dependencies (isolated --target, original env unchanged). Import failed missing libcudart.so.12. Job terminal FAILED 1:0, GPU apps before/after empty. Need preserve/check other cleanup snapshots too.
- Job 3334 submitted to install nvidia-cuda-runtime-cu12 into same target and import TransferEngine with LD_LIBRARY_PATH set to dependencies/nvidia/cuda_runtime/lib. Check current scheduler state/output before proceeding; no blind resubmission.

## Next work

1. Inspect job 3334 result, capture scheduler final and compare cleanup. Resolve specific dependency errors only with bounded small changes, no builds on head.
2. Implement bounded native P/D controller/SLURM using existing ROOT/scripts/compute_health_gate.py and cleanup pattern in local evidence/previous-controller.py. Reserve four GPUs in one job; launch separate `srun --exclusive --exact --gres=gpu:h20:2` steps for P/D so SLURM assigns devices; DO NOT override CUDA_VISIBLE_DEVICES. P=TP2, D=TP2, model len81920 MBT8192 P seq2 D seq4; APC P on D off. Disable plugins, MTP, remote reread/offload.
3. Reuse official Mooncake proxy with minimal fixes: prefill sets max_tokens=1 but must also set min_tokens=1 when Replay supplies min_tokens; bound HTTP timeouts/startup retry and preserve request IDs. Prefer `/v1/chat/completions`; client config default in modified source is chat completions (not messages). Set tokenizer_base_url directly P and metrics_url P. Review streaming TTFT and error propagation.
4. Existing client run entry: load_replay_config then run_replay(config). Set adaptive contexts, gap0.1, max_concurrency3, full selected trace, request/task/run timeouts. Existing modifications add tool_choice none, timing/session affinity/calibration. Use underlying trace unchanged.
5. Smoke max3–5 calls includes cold+continuation P APC, true transfer D no fallback, longest context. Then H/L with identical warmup/reset; formal-run ledger counts failures too. No full replay before smoke.

## Source/API notes

- Official proxy config producer `{"kv_connector":"MooncakeConnector","kv_role":"kv_producer"}` and consumer kv_consumer. VLLM_MOONCAKE_BOOTSTRAP_PORT e.g.18998 for P; proxy --prefill http://127.0.0.1:PPORT BOOTPORT --decode http://127.0.0.1:DPORT --port PROXYPORT.
- `kv_connector_extra_config.mooncake_protocol` default rdma. Existing node has RoCE; do not assume TCP/NVLink fallback without checking actual logs.
- Existing health gate checks persistent D/Z, RAM/disk/load. Existing controller uses psutil tracked pid+create_time, bounded timeout/log size and process count, graceful TERM then exact KILL. Must adapt to srun cgroups and ensure cleanup before allocation release.
- `sacct` unavailable (accounting disabled); use `scontrol show job ID` promptly after completion and save terminal state.
- Local shell tools available python3/curl; remote rg absent, use git ls-files or targeted reads, avoid wide recursive runtime scans (slow shared storage).

Previous goal turn is **progress** (trace extracted, health recovered, preflight completed, dependency installed). No repeated blocker audit threshold reached.

Update: job 3334 install finished; CUDA runtime 12.9.79 installed and `from mooncake.engine import TransferEngine` succeeded. Next inspect saved scheduler-final and any cleanup differences (read-only check in progress via local exec handle  to resolve if needed). Independent dependencies now ready; proceed to actual P/D smoke controller, not more package setup.
Final read-only check handle was 30118; consult result. Formal goal remains uncompleted, not blocked. All experiments still 0/4.

## P/D smoke attempt 3335
- Implemented scripts/pd_service.py, pd_controller.py, pd_smoke.py, pd_smoke.slurm. P/D launched in separate exact 2-GPU SLURM steps; 81920 context, MBT8192, eager, P seq2 D seq4, FP8 KV and Mooncake. Original env untouched.
- Job 3335 ended FAILED after 1m50s because monitor saw API PIDs 1139008 and 1139007 in D state at two 5s samples. Model inference was never reached. No GPU OOM or connector error observed. Need diagnose I/O before bounded restart.
- Both service cleanup JSONs have remaining=[]; controller children exited. GPU apps after empty; IPC and listening ports identical before/after; node after available memory ~2TB and load2.85. scontrol terminal saved remote smoke-3335/scheduler-final.txt.
- scripts/pd_storage.slurm reads small portions of exact model/config/runtime files inside 4-GPU allocation with timeout60, no server. Submission currently being inspected. Do not duplicate if queue active.
- scripts/replay_selected.py prepared but never invoked; formal count remains 0/4. Proxy minimal edits: bounded HTTP and bootstrap readiness, P min_tokens=1, request ID preservation, await prefill task after D stream. Need review P error propagation before production.

Storage job3336 completed0, config/code reads1–2ms and1MiB shard5ms. Smoke3337 did NOT repeat D-state fault: failed due our diagnostic entrypoint missing __main__ guard (spawn reimport). Fixed guard; both roles had remaining=[], GPU apps empty, scheduler FAILED1 terminal saved. A bounded retry of fixed script submitted; inspect newest queue/job output before further actions. No inference or formal replay happened yet.

## Latest monitor diagnosis and cleanup (21:xx)
- Smoke3338 reached TP2 workers and selected MARLIN MXFP4, loaded4/46 shards before old naive D-state monitor fired on worker TP1. Sampling evidence includes state changing from D to running between reads; storage is responsive and loading progressed. Revised monitor now requires30sec D/Z **without CPU, I/O-char or page-fault progress**, preserving memory/process/log limits and startup timeouts. This avoids equating two isolated D samples to continuous uninterruptible blocking.
- 3338 terminal FAILED. No GPU apps or matching worker PIDs after, IPC/ports identical; but four new psm files remain from aborted service: 49c5ff65,5a5da528(167772190 each),b541a7c4,f59e8307(25165836 each), all created in job3338 window. Prior wrappers45s grace exceeded srun32s termination; reduced grace15s, then exact kills.
- Added cleanup_previous_shm.py: pinnednode01, verifies old terminal evidence, absence-before/presence-after, exact owner,size,mtime window and no current same-account mappings, then removes ONLY these four files. Next smoke job runs this before healthgate. New wrapper tracks psm mappings/inodes of exact descendants and cleans after children exit.
- Need inspect current queued/running job before any resubmit. Most recent sbatch response pending in local tool handle16693. No formal run started. Source scripts locally authoritative and uploaded. Prepare formal execution only after successful3-request smoke and counter audit.

Latest authoritative observation: job3339 RUNNING on node01, elapsed2:09; P and D each loading12/46 shards (26%), progressing ~7sec/shard. Four residual psm files from3338 were successfully removed by exact cleanup before start (remote smoke-3339/previous-job-shm-cleanup.json). No step errors. Monitor fix now allows advancing weight I/O while still stopping30sec no-progress D/Z. Next turn MUST inspect3339 first, no new submission while it runs. Services not yet ready and smoke requests not yet sent. Formal replays0/4. This turn classification: progress + verified wait; no external blocker.

## Result of3339 and fix
-3339 finished FAILED after7m55. Both roles loaded all46 shards; logged model footprint74.08GiB perTP0 rank. P profiling succeeded:48.89GiB availableKV/card,663148 group-aware tokens, max81920 concurrency8.10.
-Real blocker: Mooncake RDMA initialize failed because ibv_create_cq returned ENOMEM for every mlx5_bond RNIC. Not GPU OOM or V4 weight incompatibility.
-Existing allocated-node evidence rdma-inspect3242/limits.txt: memlock soft65536, hardunlimited. Head soft/hard64KiB. Added per-service resource.setrlimit to raise ONLY soft to existing hard in allocated step, plus60s standalone TransferEngine.initialize RDMA probe BEFORE loading weights. No hostwide limits changed; no transport comparison.
-3339 cleanup verified both remaining=[], GPU apps empty, IPC/ports identical, no newly named SHM files after. scheduler-final.txt saved remote.
-Updated pd_service.py and new pd_transport_probe.py uploaded; new smoke sbatch response in handle8041. MUST inspect that job/probe before any retry. Formal replays still0/4; no smoke inference yet.

Authoritative latest: job3340 RUNNING onnode01 at0:52. Both P/D transport probes succeeded initialize_result0 with RDMA RoCE, fourmlx5_bond devices. P-memlock.json before[65536,-1], after[-1,-1] proves per-process soft-only raise, hardunchanged. Probe processes exited and removed segment descriptors. Actual model startup now in progress. Next inspect3340; do NOT resubmit. Previous turn is concreteprogress (RDMA failure resolved) plusverifiedwait. Formal0/4. P high candidate from3339 is48.89GiB/card, still need actual transfer smoke.

## Smoke accepted, first formal capacity job submitted
-3340 COMPLETED0 after11m49. Three inference requests succeeded: cold4105→8 TTFT3.363s; continuation4233→8 TTFT17.288s (startup diagnostics, not performance conclusions); longest75340→428 TTFT38.478s elapsed81.958s. Source metrics: P queries8338 hits4096 local_compute4242 external0, D external8338 local_compute0 localAPC0, no P preemptions. True P→D and P APC demonstrated. Longest total75768 covered.
-Current3340 smoke helper had already loaded before cache-reset addition; smoke-cache-reset.json absent. Reset semantics checked from installed entrypoints/serve/dev/cache/api_router.py: returns JSON success bool, false while blocks held. Formal controller now waits bounded6x5sec and requires success true BEFORE formal counter/Replay start.
-3340 exit: controller killpg(srun) sent duplicate TERM to helper processes, force-killed role wrappers (137), no per-role cleanupJSON. Fixed BOTH controllers to touch stop-services first, wrappers observe it and clean naturally; fallback single-srun TERM only after80sec. GPU apps empty and IPC/ports identical after3340;12 new psm/sem files remain, exact names/sizes/mtime window attributed in new cleanup_previous_shm.py (old3338 cleaner preserved evidence/cleanup-job3338.py). New allocation cleans those12 before healthgate/model start.
-Formal controller+replay_selected prepared/uploaded. Formal job env H=51539607552 bytes/card (48GiB), D=51539607552 fixed; intended L=12884901888 (12GiB), same settings. Whole selected174 trace, concurrency3,gap0.1,adaptive,tool_choice none, tokenizer and metrics directlyP, inferenceproxy. Two identical warmup requests then confirmedP cache reset; starts formal-runs.jsonl ledger only when Replay invoked, cap4 incl failedcomplete-run attempts.
-Removed repetitive diagnostic traceback timer by default (PD_TRACE_STARTUP optional), no inference settings changed. Service lifetime6500secs, job2h. Exact2GPU SLURM steps.
-Most recent submission response handle32630; inspect job returned there (do not duplicate). Formal started count remains0 until authoritative ledger says otherwise. Next follow firstH startup/replay then inspect results before L. No goal completion/blocking warranted; this turnprogress+verifiedwait.
First H candidate scheduler job is3341; inspect remote RUNROOT/formal-3341 and formal-runs.jsonl. No other task job currently expected. H is48GiB/card D48GiB/card.

## Formal startup3341 and dev reset endpoint
-3341 reached healthyP/D, two warmups passed: cold4105→8 TTFT1.344s, continuation4233→8 TTFT0.395s. Cache reset HTTP404 stopped controller BEFORE replay_selected or ledger invocation. Still0/4 formal starts.
-Root cause inspected in installed api_server.py lines237–240: reset_prefix_cache router only registered if VLLM_SERVER_DEV_MODE. Added VLLM_SERVER_DEV_MODE=1 in pd_formal.slurm, localhost-only binding retained. Router body returns success bool and controller checks it.
-3341 teardown now fixed: P/D/controller remaining=[]; GPU apps, ports, IPC before/after identical; zero new SHM names. TerminalFAILED1 after4m51 saved remote formal-3341/scheduler-final.txt. Prior3340's12 attributed SHM residues were removed in3341 startup; cleaner now harmless ifabsent.
-Resubmitted unchanged H48GiB/D48GiB with dev endpoint enabled; submission response pending handle21326. Follow that job, never duplicate. No formalH/Ldata yet. PlannedL12GiB; preserveallotherconfig acrossfuture H/L.
-Local scripts/pd_formal_controller.py and replay_selected.py implement warmup/reset/ledger/snapshots. Smoke3340 evidence downloaded and extracted locally evidence/smoke-3340.

## Follow-up3342 startup monitor fix
-3342 failed1 after1m23 before weightsload/replay. Optional psutil.io_counters(/proc2528179/io) AccessDenied triggered monitor, notmodelerror. Updated pd_service: optional mapsPermissionError yields no maps; ioAccessDenied recordsNone fields and still usesCPU+pagefaultprogress. Strict no-progressD/Z timeout, memory/log/processlimits unchanged.
-3342 P/D remaining=[], GPU apps empty, IPC/ports identical, no newSHM. scheduler-final saved. Submitted corrected H job withsame48GiB P/D anddevmode1. sbatch response handle63929 followup command; inspect queued latestID beforeanything. Formalledger absent, still0/4. No externalblockedcondition; progress fromfixes.
Correction3342 cleanup: new-shm assertion found ONE 32-byte sem.mp-iu4t5rt9 (not zero). H retry3343 already submitted before that check result was inspected. Subsequently performed exact cleanup INSIDE valid3343 allocation via srun (no direct node bypass), checking absent-before/present-after, owner,size,mtime window3342 and no live mapping; see formal-3343/previous-semaphore-cleanup.json. Monitor AccessDenied fix uploaded. CurrentHjob3343; follow it and formalledger. Still0/4 until replay_selected begins. Do not resubmit activejob.

## H formal replay started (3343)
- Authoritative job3343 RUNNING at elapsed6:33; formal-runs.jsonl ordinal1 H started1789826861.0757945. Formal budget now1/4, NOT0/4. P cache-reset.json HTTP200 success:true before Replay start. P/D fixed48GiB/card.
- Downloaded full replay-plan.json to evidence/formal-3343/replay. Planned sessions75+34+65=174; modes158append,13independent,3trim. Runtime session/request IDs differ from source; plan mapping is required. Actual calibration resets must also be considered for first/continuation classification once replay-execution.json exists.
- Latest request snapshot14 completed; first10 inspected allsuccess, original output lengths retained. Do not treat D cached_tokens==input as P localhit. No terminal result yet; keep3343 alive, no duplicate submit.
- H run files use replay-step.log (not replay.log). No H/L conclusion yet. Need completion, H cleanup/terminal, then L12GiB while D48GiB fixed, only after H validity review.
- Previous answer-only turn was no experiment progress; this continuation produced new authoritative evidence and is verified wait. No blocker.

## H progress and summary helpers
-3343 verified RUNNING elapsed11:18,49 requests allsuccess, latestfinished2026-09-19T14:13:40Z. No formal stderr output. Preserve activejob. Budget1/4.
-P startup logs bothTP ranks reserved48GiB/card, GPU KV cache651104tokens. Need distinguish allocated block-rounded bytes from budget if available; do not label budget exactphysicalallocation withoutsource.
-Added scripts/enrich_requests.py: finished replay plan+execution+HTTP outcomes mapped to all174originaltrace rows, includes missing/failure and actual calibrationreset cohort. Verified174plan-to-source line/session/input/output mappings onrealplan; full run awaits replay-execution.json.
-Added scripts/metric_delta.py: per-engine/label deltas, noTPsumming; exercisedreal3340smoke, reproducesqueries8338,hits4096,localcompute4242,external0,preempt0. Needrunformalbefore/afteronly.
-Executoractualpath ROOT/src/agent-infer/agentinfer/agentbench/replay/executor.py (noextra src). NodeExecution namedNodeExecution, nodes carrycontext_mode,prompt_calibration; replay-execution.json hassummary+tasks[].nodes.
-Thisturnprogress (summaryhelpers and mappingvalidation) +verifiedwait; noexternalblocker. Nextcontinue3343 untilterminal,collectcleanup/scontrolpromptly,inspect174thenL12GiB/D48GiB.

## Capacity reporting evidence,3343 ongoing
-3343 RUNNINGelapsed14:16,72/174requestresults,all72success,latest2026-09-19T14:17:09.733433Z. Noformalstderr. No new formalrun,still1/4.
-Added evidence/capacity-interpretation.md: H explicit48GiB/card logs worker capacity651104tokens but formal-before-P.prom cache_config_info reports49572GPUblocks,resolvedminimumblocksize4,scheduler-config260116tokens,maxconcurrency3.17525. Runtime core.py308–319 recomputes after generate_scheduler_kv_cache_config, which replacesUniformTypeKVCacheSpecs withfirstcontainedspec; log uses workerconfig. Preserve bothrawtokenfigures,bytesbudgetprimary,do not inferphysicaltensorallocationexactbytes. No runtimepatchneeded.
-Previous turn progress+verifiedwait; currentsame. Follow3343; Hfinish+cleanup+terminalneeded beforeL.

## H ongoing, summary script ready
-3343 RUNNINGelapsed18:14,107/174requestresults;previousfullstatuscountat101wasallsuccess. Noformalstderr. Do not resubmit. Budget1/4.
-Added scripts/summarize_point.py combining enrich_requests and metric_delta, extracts actualcache_info blocks/schedcapacity/budget, localcompute/external/preempts, cohortTTFTlinearP50/P95/counts, failure/missing and lengthmismatchcounts; writes requests-enriched.csv,metric-deltas.json,point-summary.json. Only syntaxchecked, mustrunagainstcompleteH/Lbeforetrust. Requestwindowduration explicitlynamed, distinct totalreplayduration(takeexecutiontasks/resultslater).
-Systempython3 hasmatplotlib3.9.4, useMPLCONFIGDIRunderworkspaceor/tmp forplots. Bundledruntimepython lacks matplotlib; noinstallneeded.
-Thisturnprogress (summaryscript) +verifiedwait. Nextcontinue3343; finishcoverage/cleanup/schedulerterminal thenL12GiBwithD48GiBunchanged.

## Plot preparation while H runs
-Added scripts/plot_capacity.py: reads point-summary.json files, writes summary.csv and two scatterplots onlymeasuredcomplete174successpoints; nofittedline. NeedrealH/Ldataandvisualinspectionbeforefinal. UseMPLCONFIGDIR=/tmp/pd-capacity-mpl python3(systems3.9hasmatplotlib3.9.4).
-3343stillrunning, latestpoll resultin currentturn; formalbudget1/4. Prior20:59elapsed127rows,119statuscheckallsuccess. No restartornewsubmission. Thisturnprogress+verifiedwait.

## H complete and L submitted
-3343 COMPLETED0, runtime30:02,174/174successful across3sessions; nofailed/skipped/pre-sendfail. Inputcalibrationall174exact,noreset; actualinput/outputlengthallmatchtrace. P/Dremaining[],controllerremaining[],gpuappsnone,ports/ipcsame,newshmnone; memoryavailable2004067MiB,storage52%,load4.63. scheduler-final.txtremote+local.
-Downloaded/extracted evidence/formal-3343-evidence.tgz and ran summarize_point.py successfully. Hquery6977618,hits6457088,hit92.540004%,localcompute520530,externalP0,Dlocalcompute0,Dexternal6977618,preemptsP/D0. 13firstTTFTP50=8.65985 P95=31.55063;161continuationP50=.6938535 P95=25.68925. Requestwindow1503.729s. point-summary.json,requests-enriched.csv,metric-deltas.jsonlocal.
-Head/SLURMpre-submithealthy:2nodesidle,noourjobs,memoryavailable2747MiB,load.26,storage52%; currentawkbriefD0elapsed notpersistentorhealthregression. Existingcomputehealthgate+snapshotwillruninsideallocation.
-Submitted L withP12884901888(12GiB)andD51539607552(48GiB),samepd_formal.slurm. Toolhandle37238response inspectedinthisturn. Followreturnedjob; do notduplicate. Formalcountstill1untilLreplayledgerentry.
-FullHmetricsvalid; mustfinishL+cleanup,compareconfigs,generatefinalreport/csv/plots,savebothremote/localbeforecompletion. No goalcomplete/block.

Latest L jobID3353. Mustfollow3353,not3343(completed).

## L loading3353, H report drafted
-3353 RUNNINGelapsed3:36 Ploaded23/46shards50%,progress~6sec/shard,noformalstderr. LedgerstillHonly1/4;Lformalnotstarted. Follow3353,no duplicate.
-Updated summarize_point.py addsreplay_task_window_seconds and actualinput/outputsum. Re-ranH;1504.231511secs,6977618input,28416output. Uploadedall4summary/plothelpers+capacitynote toBASE,andHpoint-summary,requests-enriched,metric-deltas,summary-validation intoformal-3343.
-Created localREPORT.md withHresults,scope,commands,definitions,cleanup and explicitlypendingL; notfinalreportyet. NeedcompleteLcompareconfigs/fingerprint andfinishfigures/report,copyfinalremote+local.
-Thisturnprogress+verifiedwait. No goalcompletion/block.

## L formal started3353
-3353 RUNNINGelapsed7:56; cache-resetHTTP200success:true; ledgerordinal2Lstarted1789828884.103316. Formalbudgetnow2/4.21requestrowslatest.
-Runtime Pcache_info12884901888bytes,12393GPUblocks(quarterH49572),scheduler-config65029tokens,minblocksize4. Lstarted successfully; mustletfulltracepressurecheckrun. No context/config changes.
-H/Lactualservicecommandscompared:onlyPkv_cache_memory_bytes48to12GiB,Dcommandidentical. Local evidence/hl-config-comparison.json.
-JITlimitations: H P.logformalwindowwarnings22:08:03TileLangmhc_pre_big_fuse_broadcast_with_norm_tilelang and22:19:05Triton_build_prefill_chunk_metadata_kernel. D warningsonlywarmup22:07:36–37; LwarmupalsoJIT. Retaininreport; do not attributeallTTFTdifferencepurelycapacity. Noadditionalprofiling/repeatrequiredbydefault.
-Thisturnprogress(configcomparison,capacityactualverified) +verifiedwait. Nextfollow3353,notnewjob; HcompletebutgoalincompleteuntilvalidL+report/figures+cleanup.

## L verified wait
-3353stillRUNNING,49rowsat9:51elapsed,nocontrollerstderr. Earlier32statuscheckallsuccess,Ptransferlogfailures0,recvs0,expired0. Latestpollinthisturnfollows. Keepjoblive,no newsubmissionor configchanges. Formalbudget2/4.
-Thisturnverifiedwaitonly; noexternalblocker. Hfinishedlocal/remoteartifactsandREPORTdraftready. NextLcompletionbeforecomparison.

## L half complete
-3353 verifiedRUNNINGelapsed14:38,90/174HTTProws; fullstatusat78all78success. Noformalstderr; PAPIstillacceptingrequests200. Capacity/D/workloadunchanged,formalbudget2/4.
-Thisturnverifiedwait(specificliveSLURMjob); no blocker/no restart. Nextfollow3353throughcompletionandcaptureterminal+cleanupthenreportcomparison.

## L ongoing3353
-VerifiedRUNNING17:14elapsed,108/174allsuccess; finalpollinthisturnmorecurrent. Dlivegeneration3requests,nostderr. Formalbudget2/4. No configchanges/extraexperiments.
-Thiscontinuationverifiedwait(specificlivejob3353),no blocker. FinishLthenharvestfullresultsandshutdownbeforeH/Ldecision.

## L near final quarter
-3353 verifiedRUNNINGelapsed21:01,134/174allsuccess,latest2026-09-19T14:55:35Z; finalpollinthisturnmorecurrent. Ptransferfail/expired0,noformalstderr. Budget2/4.
-Thisturnverifiedwaitonly; nextfollowlive3353,no duplicate. StillneedLcompletion/cleanup+H/Lreportplots.

## H/L completed, final artifacts prepared
-3353 COMPLETED0 runtime29:13,174/174success,noerrors/skips,alllengthsmatch. P/D/controllerremaining[],trackedPIDsabsentinafterps,gpuappsempty,ports/ipcsame,newshmnone,healthyfinalmemory/storage. scheduler-finalremote+local. Localarchiveextracted.
-Lquery6977618,hits6266624,hit89.81036%,localcompute710994,Pexternal0,Dlocalcompute0,Dexternal6977618,preempts0.13firstTTFTP502.71148,P9517.52583;161continuationP50.6621934,P955.228696. Replaytaskwindow1339.520s.
-HvsL:hit+2.729642pp,localcompute-26.7884%,TTFTP50improvement-4.7811%,P95-391.3129%. FollowpredefinedstopcaseincreasedreusewithoutTTFTbenefit:stopat2formalruns,noM/repeat. JITbothformalwindows/closedloop/singlerunlimitsnotcausalcapacityslowdown.
-REPORT.md rewrittenfinal,results/summary.csv+2PNGgeneratedandvisuallychecked. H/Lplansidentical,replayconfigidenticalexceptresultdir,174originaltraceIDsmatched,onlyPbudgetchanged. evidence/completion-audit.json assertsfullcoverage,unchangedselectedsource,reset,terminal,aftertrackedpids/portsGPUIPCshm,artifactpresence.
-Model-config+client-existing.patch+formalledgerdownloaded. Bundle results/final-deliverables.tgz uploadingtoBASE inhandle61847; nextmustfinishupload,extractintoBASE/final-report,verifyreport/csv/pngand2pointdataremotely. Thencompletionauditcompleteandupdate_goalcomplete. NoGPUjobsleftfromthisexperiment; otherjob3358sameaccountseen,do nottouch.

Final delivery verified remotely at BASE/final-report: report,summary.csv,twoPNGs,174rowsperpoint,schedulerterminals. Allgoalrequirementscompleted;2/4formalbudgetused,nofurtherjobsneeded.
