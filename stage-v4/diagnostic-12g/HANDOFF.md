# L3 作业3442定时验收

## 当前任务
用户授权一次新425计划的12GiB定向补测，检查L2/3430的低复用/长尾及额外查询；随后明确要求不全程盯守，提交后定时验收。24/48不重跑，不下载完整周期metrics。不自动重试。

- 作业3442，2026-09-20 17:07:04北京时间开始，节点vllm-h20-01，四H20，32CPU/512G，2小时上限，最迟19:07:04。
- 预计按L2耗时约18:10完成，自动化`12-gib`于18:30运行验收（当前任务heartbeat，COUNT=1）。如仍运行，应有界延期一次；处理完成或失败后停用。
- 服务器ROOT=/home/david_cwq/zhouziheng/agent-replay-20260917。
- BASE=$ROOT/evidence/pd-capacity-20260919；D=$BASE/stage-v4/diagnostic-12g；RUN=$D/formal-3442。
- 本地对应目录stage-v4/diagnostic-12g。

## 启动与健康
提交前head异常高load已归属已知Codex reconnect D进程；按用户例外做一轮精确SIGTERM，无重复cleanup。初次脚本随后在Python3.6 text参数处失败，后续只读复查，无二次kill；head-before.json显示当时已无匹配残留，load1降至1.29，SLURM正常。不得因这类已知残留重现取消实验。
计算节点preflight通过：192CPU、load0.66、可用内存约2TB、存储约4.9TiB；唯一长期root dmesg Z是已确认基线，瞬时root sh已消失。
作业由原controller和服务wrapper的独立副本运行，保留有界等待、进程/内存/日志监控、stop-services、精确PID及shm清理。结束时必须检查P/D-cleanup、controller-cleanup、GPUapps/ports/ipc前后、SLURM终态，不以jobexit0单独判定清理完成。

## 配置与诊断
425 trace、make_config、请求发送逻辑沿用stage-v4；P12GiB/D48GiB、maxseq2/4、客户端3，超时5400/5700/900不变。标签L3独立一次性账本，不改旧实验记录。
P服务增加专用PYTHONPATH hook，不修改安装的vLLM。hook包装KVCacheManager.get_computed_blocks、allocate_slots、Scheduler.schedule及connector匹配调用，透传参数与返回值。Python语法与模拟调用透传检查通过。预热后controller要求看到lookup诊断事件才进入正式回放。
query-diagnostic-PID.jsonl：
- lookup: request_id、num_tokens/num_prompt_tokens、num_computed_tokens、preemptions、hit_tokens、查找耗时。
- allocation_none: num_new_tokens、新命中量、free_blocks等。
- lookup_decision: allocation、external_tokens/async_load、未准入原因、scheduled_tokens、running/waiting、adopted_local_cache_tokens。
- scheduled_totals: 每10秒调度token累计快照（不是GPU实测FLOPs或物理工作量）。
- installed/scheduler_config确认注入与配置。
查询后未调度分支分类包含connector_match_pending、aligned_chunk_zero、allocation_none和async_load_or_other_unscheduled；最后一种仍需结合源码细化，不能自动归为分配不足。
源码快照：source/v1/core/sched/scheduler.py、kv_cache_manager.py、metrics/stats.py、loggers.py。已有5个冻结源码与当前安装文件比较全部相同（runtime-source-comparison.json）。新取回scheduler/manager没有旧完整快照，不能声称它们也已逐字比对。

## 验收步骤
1. 从head squeue/sacct/scontrol查3442，不越过SLURM直接进计算节点。
2. 检查启动/回放失败日志；下载少量配置、正式窗口before/after prom、请求结果/计划、query-diagnostic日志、清理证据。**不下载完整metrics-samples.jsonl**。
3. 425/425、长度完全匹配、执行计划与L2一致；核对物理GPU分配及运行参数差异仅hook。
4. 使用正式窗口起止（formal-metrics采集与event boundary及replay manifest）过滤诊断，排除2个预热请求。按请求query次数和token累计求和，对齐P prefix counter。命中求和也对齐。请求ID需经proxy日志关联客户端ID。
5. 对每个request：重复次数/额外query、未准入原因、命中量、最后采用缓存量、首次查询至首次调度等待；汇总额外query是否集中零/低命中请求。不要把重复查询等同于重复计算。
6. 报告L3与L2的query/input差值、来源缓存占比、local_compute、prefill、后续轮TTFT、E2E、任务窗口；只判断退化是否同量级重现，不要求数值相等。必要较重分析在本地或明确有界SLURM CPU作业运行。
7. 生成DIAGNOSTIC-REPORT.md，保留L2原结果。若证据不闭合明确写未解释，不无限追查/自动重跑。完成后停用自动化12-gib。

## 已确认旧新差异
旧L/3415 vs L2/3430：425共同sourceID/长度/依赖相同，但全部派生采样seed及12份抽查长prompt文本改变。源文件hash参与session namespace再影响filler与samplingseed。已有12GiB-discrepancy-review.md说明。
old-new-timing.json按旧成功提交顺序分段，200–300段相同源请求的续接TTFTP95旧5.36s、新20.21s；前100条旧8.46、新7.30。旧长输出请求入场前已完成390条续接，旧P958.57、新同ID15.98，因此长输出占用并发不能单独解释早期/中期差异。该分析非固定访问序列因果证明。

## 原始比较值
L2/3430：query15666148,input13707996,hit6605312,compute7102684,移除623629,prefill3.395204705,续接395/P501.769222842/P9515.957651251,E2EP9572.182983482,窗口3245.487976s，preemption0。
M/3429：query13707996,hit12449536,compute1258460,prefill.656442022,P952.899705207,窗口2720.669884s。
H/3425：query13707996,hit12630784,compute1077212,prefill.570242914,P952.725425853,窗口2698.078781s。

## 提交后的最后检查（约17:12）
3442 RUNNING，模型加载完成，正在kernel warmup。P/D的设备UUID与完整启动command均与L2相同（config-comparison-L2.json）。当时尚未看到诊断JSONL；Scheduler在EngineCore初始化后创建，预热后controller强制校验lookup存在，否则退出而不进入正式回放。用户要求提交后定时验收，不再持续盯守。自动化12-gib已创建并通过view及本地toml核实为ACTIVE、18:30单次触发。

## 18:30验收已完成
L3 425/425，输入缓存占比81.48%、TTFTP95 7.244s，L2严重退化未复现。437次查询中12次allocate_slots=None且零命中，额外346790 query完全对账；逐请求累计调度token等于输入减最终缓存。本次诊断及报告已完成，自动化停用。详见DIAGNOSTIC-REPORT.md；没有新增GPU运行。
