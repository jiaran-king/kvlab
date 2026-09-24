# 四张 H20 的 P 侧 KV 容量对照

**两次正式回放已完成。P 每卡 KV 预算从 12 GiB 增加到 48 GiB 后，本地命中率增加 2.73 个百分点，本地输入计算计数减少 26.79%；这次运行没有观察到后续轮 TTFT 收益。** 两档均完成全部 174 条请求，没有失败、超时、跳过或抢占。

本轮到此收尾，不追加 M 或重复运行。结果符合预先规定的“复用增加但 TTFT 未改善即可结束”条件；不要求正收益，也不据此推断 AFD 实际加速比。

## 完整对照

| 指标 | L（作业 3353） | H（作业 3343） |
|---|---:|---:|
| P KV 预算／卡 | 12 GiB | 48 GiB |
| P GPU blocks | 12,393 | 49,572 |
| P 本地命中率 | 89.8104% | 92.5400% |
| P 本地命中 token | 6,266,624 | 6,457,088 |
| P 本地输入计算计数 | 710,994 | 520,530 |
| 首次／reset 样本量 | 13 | 13 |
| 首次／reset TTFT P50／P95 | 2.711／17.526 秒 | 8.660／31.551 秒 |
| 后续轮样本量 | 161 | 161 |
| 后续轮 TTFT P50／P95 | 0.662／5.229 秒 | 0.694／25.689 秒 |
| 成功／失败／未发送 | 174／0／0 | 174／0／0 |
| P／D 抢占 | 0／0 | 0／0 |
| 回放任务窗口 | 1339.520 秒 | 1504.232 秒 |

两档查询量均为 6,977,618 token，实际输出均为 28,416 token；全部请求的输入、输出长度逐条符合计划。P 外部 KV 计数均为 0；D 本地输入计算均为 0，D 外部 KV 接收均为 6,977,618 token。P 本地命中率使用正式窗口内 token 加权计数，没有使用 D 响应中的 cached_tokens。

H 相比 L 少计算 190,464 个本地输入 token。TTFT 改善率按 `(L−H)/L` 计算，后续轮 P50 为 **−4.78%**，P95 为 **−391.31%**。负数表示本次 H 更慢，不能解释为增大缓存必然使系统变慢。首次请求也表现出较大运行间差异。

每档只有一次闭环回放，尚未评估运行间波动。相同释放规则不保证实际请求交错相同；生成反馈和 adaptive 校准也不保证请求内容逐字相同。H 和 L 正式窗口中均有 JIT 编译警告，预热没有覆盖所有形状；两个作业复用既有磁盘编译缓存。因此，这组数据支持“更多容量伴随更多 P 本地复用、更少本地输入计算”，**不足以将 TTFT 差异单独归因于容量**。没有剔除慢请求，也没有为了得到正结果更改负载。

## 两张图

只画 L/H 两个实测有效点，不拟合曲线、不宣称已找到饱和点。

![P 本地命中率](results/capacity-hit-rate.png)

![后续轮 TTFT](results/capacity-ttft.png)

## 配置与测量口径

同一节点 vllm-h20-01、四张 NVIDIA H20-3e（每卡 150,110,011,392 字节），一个 P 实例 TP2、一个 D 实例 TP2，即 1P1D。SLURM 分配 GPU，不覆盖其设备可见性。模型沿用 `/home/david_cwq/jinghaoyu/models/DeepSeek-V4-Flash`，加载日志显示 `quantization=deepseek_v4_fp8`、基础 dtype bfloat16、FP8 KV；模型配置快照另行保留。该本地模型目录没有在启动参数中声明远端 revision，不能把目录名当作已验证的 Hub 提交号。

固定 vLLM 0.26.0、Mooncake RDMA、eager、上下文上限 81920、MBT 8192、P max_num_seqs=2、D=4、P APC 开启、D APC 关闭。无投机解码、AFD、D→P 跨轮回读或 KV offload。D 每卡预算始终为 48 GiB。对比实际服务命令，唯一变化是 P 的 `--kv-cache-memory-bytes`；Replay 配置除输出目录外完全一致。

每档使用相同两条预热请求，等待完成后，P `/reset_prefix_cache` 均返回 `success:true`，随后采集起始 metrics、正式回放和终止 metrics。smoke 的三条请求已验证真实 P→D 传输、本地 APC 和最大上下文：第二轮观察到 P 本地命中 4096 token；D 输入全部来自外部 KV；最长请求输入 75340、输出 428，总计 75768 token。

TTFT 使用客户端流式请求开始至首个有效生成内容的计时，不包含回放的人为等待间隔。首次／后续轮依据上下文续接关系和实际 reset 信息划分，并非仅删除每个 session 的第一条；本次无实际 reset，13 条独立请求、161 条后续请求。分位数采用线性插值。回放任务窗口从首个任务入队至最后任务完成；HTTP 请求窗口另存于 CSV。

本地输入计算使用运行时 `prompt_tokens_by_source_total{source="local_compute"}` 差分，是输入来源计数，不宣称覆盖所有物理重算。counter 保留 engine 标签；本部署各 role 只有一组 engine=0 指标，没有累加 TP 重复计数。

容量用运行时确认的每卡字节预算和 block 数描述。H/L block 数为 49,572／12,393，实际池规模确有四倍差异。日志 worker-config token 容量为 651,104／162,776，metrics scheduler-config 为 260,116／65,029；两者输入配置不同，不混用或乘以 TP 卡数。未采集精确物理 tensor 字节合计，字节预算不冒称精确分配合计；分组逐 tensor 细节不在本轮范围。详见 `evidence/capacity-interpretation.md`。

## 固定负载

AgentInfer commit：`7f304555a8bc504c2c2257db2662e896eeeb5c30`。源文件 `tests/agentbench/replay/claude_trace_8session_requests.jsonl`，三个完整 session：

- `66fd0455-0715-4b7b-ab93-d2aeb4323268`：65 条。
- `c4d23e13-7f6c-4998-af37-d6a3e8b4067f`：75 条。
- `7aefcc2d-844d-4445-b575-350f065a0a52`：34 条。

并发 3、seed=0、同 actor 间隔缩放 0.1，`prompt_shape=claude_code_minimal_v1`、adaptive 上下文构造，保留原始输出长度。源记录没有裁剪或复制。两档 Replay 计划完全一致，已按原始 trace ID 对齐全部 174 条记录。这是 synthetic Trace Replay，不执行真实工具，不是原生产时序和文本内容的完整重现。

## 复现命令与产物

远端工作目录：`/home/david_cwq/zhouziheng/agent-replay-20260917`。
证据目录：该目录下 `evidence/pd-capacity-20260919`。保留模型配置、既有客户端修改 `client-existing.patch`、启动脚本、proxy、运行配置及日志。本轮使用隔离的 Mooncake 依赖目录；代理小修和服务生命周期处理均在脚本内留档，未开发新 connector 或内核。

已执行命令（不要因查看报告而再次提交）：

```sh
sbatch --export=ALL,CAPACITY_LABEL=H,P_KV_BYTES=51539607552,D_KV_BYTES=51539607552 /home/david_cwq/zhouziheng/agent-replay-20260917/evidence/pd-capacity-20260919/pd_formal.slurm
sbatch --export=ALL,CAPACITY_LABEL=L,P_KV_BYTES=12884901888,D_KV_BYTES=51539607552 /home/david_cwq/zhouziheng/agent-replay-20260917/evidence/pd-capacity-20260919/pd_formal.slurm
```

本地重算汇总（在本报告所在目录运行）：

```sh
python3 scripts/summarize_point.py evidence/formal-3343 evidence/selected-trace.jsonl H
python3 scripts/summarize_point.py evidence/formal-3353 evidence/selected-trace.jsonl L
MPLCONFIGDIR=/tmp/pd-capacity-mpl python3 scripts/plot_capacity.py results evidence/formal-3343/point-summary.json evidence/formal-3353/point-summary.json
```

`results/summary.csv` 包含完整指标；`evidence/formal-3343` 和 `evidence/formal-3353` 各含逐请求 `requests-enriched.csv`（原 trace ID、session、actor、轮次、状态、实际长度和 TTFT）、原始 Replay 输出、metrics、服务配置、日志与清理证据。`evidence/hl-config-comparison.json` 和 `evidence/hl-comparison.json` 保存配置、计划及 ID 对齐结果。远端同名作业目录直接位于证据目录下。

## 收尾与验收

H 作业 3343、L 作业 3353 均为 `COMPLETED`、退出码 0:0。每档均在分配内停止服务：P/D/controller 剩余进程列表为空、GPU 应用为空、端口及 IPC 与运行前一致、无新增共享内存残留；内存、存储及负载没有本轮引起的异常。控制节点已确认两份作业终态，保存 `scheduler-final.txt`。不清理或干预其他同账号作业。

正式台账仅两次回放，未运行第三、第四次。启动和 smoke 阶段的失败及修复保留在原目录中，没有作为正式有效点。有效 H/L 对照、表格、图、逐请求数据、命令与清理证据均已交付；结论停留在证据支持的范围内。
