# Stage v5 自动三阶段验收

用户授权一次安排C12/F12/F24，按验收依赖自动推进，无需逐阶段确认。不自动重试、不补交替代GPU作业。

已于2026-09-20北京时间21:12提交：
- C12：3454，P12 GiB，原425闭环；run formal-3454。
- F12：3455，afterok:3454，P12 GiB，冻结formal-3454输入。
- F24：3456，afterok:3455，P24 GiB，同一冻结输入。
- 3457为1 CPU/2 GiB/3分钟的终态记录作业，afterany:3456，不使用GPU。

每GPU作业4H20、32 CPU、512GiB、2小时。目标节点vllm-h20-01。服务/客户端参数沿用旧425协议；D48GiB。脚本在退出前清理并检查真实P token与请求体/查询/采用计数，成功才写ACCEPTED.json和退出0；afterok因此包含证据门槛。依赖失败时--kill-on-invalid-dep=yes取消后续。不要重新提交。

本地：/Users/zhouziheng/Documents/ChatGPT/replay/stage-v5
远端：/home/david_cwq/zhouziheng/agent-replay-20260917/evidence/pd-capacity-20260919/stage-v5
仅用系统ssh vllm-h20-head，持续分析在本地或有界CPU allocation。不要开启Codex persistent SSH。

## 验收动作

1. 轻量读取squeue/sacct/scontrol及submitted.json、scheduler-terminal.json、各作业exit-code/ACCEPTED/cleanup-audit；及时保存终态。3457保存三GPU作业终态。若该作业未触发，需从head补读，不能把控制器退出码等同终态。
2. 运行或排队且无异常时不持续追日志；保持安静。首阶段查看services-ready、capture-smoke、计算节点health-gate是否通过，留存P/D实际资源。只能经已有allocation访问计算节点。
3. 任一失败，保留traceback、已采集证据与清理/健康状态，确认后续依赖被取消；仅取消本链中无法继续而仍挂起的精确作业ID，不影响其他作业。不修补服务、不重试GPU、不修改运行中观测代码。失败立即报告并停用监控。
4. 全部完成后取回小型请求/诊断/输入索引/配置/指标端点/清理产物。实际输入数组约55MB且分析必需，可取回；请求体较大，优先留服务器，必要时再取。**不下载完整周期metrics或大KVEvent**。优先复用observer末状态、完整窗口摘要；需要全事件流计算分组总量时，单独有界CPU作业，只回传摘要。
5. 各运行425/425；按context_after计算运行内实际P输入LCP并关联query attempt、group联合调用与最终采用。F12/F24 token数组与语义身份已由门禁比较，独立核对其结果。不是固定执行顺序。
6. 生成per-request/paired-requests.csv：全部正负零delta_A，净和对齐正式local_cache_hit差；local_compute、external单列。按请求/actor报告净收益来源，不能仅选样例。查询计数不是最终采用，group联合返回不是独立group最大命中。
7. 输出summary.csv和REPORT.md。历史矩阵缺项见historical-matrix-supplement.json已补齐。C12、F12/F24与历史L2/L3/M/H协议分开；不以新运行声称历史L2根因已还原。首次成功调度非GPU开始；发送后TTFT不含客户端槽位等待。槽位入队至首token逐请求算再求分位数。
8. 完成/失败后停用本自动化。只在完成、失败或需要用户处理时通知；中间进度无须逐次通知。预期00:00–01:00结束，若排队延后按实际状态解释；最晚2026-09-21 05:30回报未完边界，不自动扩展监控或提交实验。

## 代码与验证

CPU验证记录cpu-validation.txt：原函数调用一次、完整tuple身份与共享前缀元数据透传；attempt/group序号关联；输入按请求只记录一次；不同模拟回答不影响冻结请求，无动态构造调用。语法检查通过；SLURM --test-only通过。

source/来自2026-09-20目标安装源码，仅本轮参考；每作业snapshot_runtime.py比较源码并保存source-identity.json。配对要求观测代码指纹不变。因此**三阶段运行期间不要新增/改动远端stage-v5的Python文件**。可在本地准备分析程序，待三阶段终态后上传。

已知head Codex重连D残留按用户例外处理一轮，记录head-submit.json，不阻塞健康的实验也不重复清理。compute完整健康/服务清理仍必须核对。

自动验收已创建并通过view确认：h20-v5，ACTIVE，每小时30分检查，最多8次；完成/失败后停用。C12提交后21秒已RUNNING且计算节点preflight通过，F12/F24/终态CPU任务均在Dependency等待。最终服务ready及正式smoke由controller和后续自动验收确认。

## 21:30验收终态
C12/3454在21:20:16因观测smoke断言失败，正式回放未开始；F12/3455及F24/3456由SLURM依赖失败自动取消。两条预热均完成，但落盘只有一次lookup_decision，发现缓冲写日志与立即读文件验收之间缺少flush确认；尚未证明唯一机制。已保留失败及清理证据，cleanup-audit通过，h20-v5已PAUSED。未修改代码、未重跑。见REPORT.md。后续继续需要明确新的修复/运行授权，不按本交接前文自动推进。
