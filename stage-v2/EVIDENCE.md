# 第二阶段证据索引与完成核验

核验对象是 NEXT_GOAL.md／目标附件的完整范围。四次正式回放已结束，证据支持 L/H2 的完整负载工程对照；M 失败，三档完整可比响应没有取得。默认争取三档并非强制找齐拐点，预算内两次新增均有预先用途且已执行，失败按要求保留。没有把 M 的成功样本当作中间有效点，也没有因预算耗尽将未完成测量冒称成功。

| Goal 要求 | 权威证据与核验结果 |
|---|---|
| 只变 P 容量、固定 D 与推理配置 | 四份 P/D-config.json、formal-before-P/D.prom；旧 evidence/hl-config-comparison.json；新增 formal-3384、formal-3391 的 comparison-to-L.json。命令只有 P 预算不同，D 48GiB，block 数分别12393/24786/49572。 |
| 同节点四卡、P TP2＋D TP2 | 各 job-before.txt、devices.csv、topology.txt、P/D-config.json 的 job/step/cgroup/设备。均 node01 四卡，物理UUID未固定的限制已披露。 |
| 模型、运行时、patch 沿用 | evidence/model-config.json、client-existing.patch、source-comparison.json、head-before.txt、remote-scripts/及加载日志。相关正式脚本与patch一致；未升级或重建环境，未散列全部权重。未使用的旧smoke controller差异明确说明，不影响formal路径。 |
| 原三个完整 session、174 条计划和固定规则 | evidence/selected-trace.jsonl；四份 replay-plan/config、execution、requests-enriched.csv。计划一致且各逐请求映射174唯一ID；H/L/H2全成功且长度匹配；M160成功长度匹配、1超时实际计数缺失、13依赖跳过。未裁剪计划或改输出。 |
| 最小旧点审查及选择依据 | DECISION.md、tail-pairs.csv、compile-intervals.json、jit-transfer-events.json、review-facts.json、stage-means.csv。包含H最慢10条与L同ID及L自身尾部，时间基准、在途数与现有阶段统计；无token全文则明确无法验证内容等价。 |
| 限定完整Replay次数及复核不择优 | formal-runs-final.jsonl恰H/L/H2/M四条；replay_selected.py在调用前锁台账。H2和M用途在各自启动前记录，先审H2再决定M。所有结果逐次保留，无第五次、免费全trace预热或快点替换。 |
| 原预热、清缓存和完整指标窗口 | 四份warmup-completed.json均2请求，cache-reset.json均HTTP200/success:true；formal-before/after-P/D.prom。结束running/waiting均0；controller源码顺序已审阅。 |
| 容量与缓存／来源统计口径 | metric-deltas.json、起止prom、summarize_point.py和metric_delta.py；每role一组engine序列，不累加TP。预算不冒称tensor分配，counter来源和直接／推导属性在CSV／报告明确。M覆盖不同，不纳入主缓存比较。 |
| 延迟、首次／后续、E2E、完成时间 | 各requests-enriched.csv及point-summary.json；四份supplement；summary.csv数值逐项与per-run JSON一致。原线性分位数、按上下文及reset分组；M成功样本明确标记，不填补超时TTFT，不池化跨run请求。 |
| 失败和缺失呈现 | M replay-execution.json确认161尝试160成功1失败13跳过；D日志2条rank记录同一内部request。报告保留客户端与内部ID但不伪造关联；CSV含timeout和skipped，图标M incomplete。D无周期汇总为缺失，直接KV错误另计。 |
| 现有阶段诊断 | H/L/H2/M-supplement.json、results/stage-means.csv；sum/count差分样本分别174/174/174/160。无阶段P95相加，无gauge均值／峰值推断；未开发profiler、模拟器或新观测系统。 |
| 有限启动及服务器健康 | DECISION.md预设45分钟/最多3启动尝试，本阶段两次各一次成功；pd_formal_v2.slurm固定4GPU、32CPU、512G、2h及锁。head-before、head-before-M和各health-gate、前后快照记录。已知reconnect例外按既有授权处理，未修改远程连接或调度系统。 |
| 归属与双阶段清理 | P/D/controller-cleanup.json及实际after进程、GPU、端口、IPC/shm、内存/负载/存储快照；scheduler-final均COMPLETED0:0。新增cleanup-audit证实本轮PID已无、服务端口释放。M新增12共享内存通过inode/maps归属3392/3393及对应端口进程树，见other-resource-attribution.jsonl。未清理其他作业。只读无GPU核验3396亦COMPLETED0:0。 |
| 报告、表、两图及证据 | REPORT.md包含所有运行表、端点差值、M失败、协议、解释与复现命令；results/summary.csv和两PNG均已生成并目视检查。completion-data-audit.json保存四运行覆盖、reset、终态、结束gauge及CSV一致性核验。原始H/L与旧报告未覆盖。 |
| 结论边界与停止 | 可比较完整端点L/H2已取得；缓存增加与TTFT分位数变化据实报告，稳定性/归因/knee/saturation未证明。M失败使三档目标未取得，不进一步推导边际递减。全部授权回放及交付结束，不扩展研究或突破预算。 |

本地根目录 `/Users/zhouziheng/Documents/ChatGPT/replay`。本地旧运行在 `evidence/formal-3343`、`evidence/formal-3353`；新增运行在 `stage-v2/formal-3384`、`stage-v2/formal-3391`。原始文件是权威来源，本索引不替代文件。

远端 BASE 为 `/home/david_cwq/zhouziheng/agent-replay-20260917/evidence/pd-capacity-20260919`。旧运行在 BASE/formal-3343、BASE/formal-3353；新增运行在 BASE/stage-v2/formal-3384、BASE/stage-v2/formal-3391。报告、图表、统计脚本和派生数据归档在 BASE/stage-v2/final-delivery，旧证据继续复用。归档交付另存 delivery-verification.json 以确认实际文件已保存。

完成判断：预算内的容量benchmark、异常审查、实测及报告交付完成；不是宣称24GiB测量有效或三点完整响应已完成。当前证据足以进行L/H2的单次工程比较，故不触发“连延迟可比条件都无法建立”的部分完成条件。任何后续重跑或传输问题修复需要新范围和预算。
