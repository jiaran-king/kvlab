# 24 GiB M2 补测与最小故障定位

**M2 完成174/174请求，原失败未复现。24 GiB与48 GiB的本地命中及local compute计数完全相同。** 在当前负载的单次工程观察中，12→24 GiB已经获得此前12→48 GiB的全部缓存计数收益；24→48 GiB没有进一步增加命中，后续TTFT P95仅相差约23毫秒。

本阶段先审查M1，再按事前决定执行一次完整M2，没有直接盲重跑。未修复或改动Mooncake状态机，也未证明原故障已消除。M1完整保留。新授权的一次正式回放预算已使用，不追加实验。

## 三档有效结果

| 指标 | 12 GiB／L | 24 GiB／M2 | 48 GiB／H2 |
|---|---:|---:|---:|
| 作业ID | 3353 | 3406 | 3384 |
| P block数 | 12,393 | 24,786 | 49,572 |
| 成功／失败／跳过 | 174／0／0 | 174／0／0 | 174／0／0 |
| 本地命中率 | 89.8104% | **92.5400%** | **92.5400%** |
| 本地命中token | 6,266,624 | **6,457,088** | **6,457,088** |
| local compute token | 710,994 | **520,530** | **520,530** |
| 后续TTFT样本 | 161 | 161 | 161 |
| 后续TTFT P50（秒） | 0.6622 | 0.6869 | 0.6989 |
| 后续TTFT P95（秒） | 5.2287 | **3.9716** | **3.9486** |
| 独立请求TTFT P50／P95（秒，n=13） | 2.7115／17.5258 | 1.7285／17.3966 | 1.7547／17.5702 |
| E2E P50／P95（秒，n=174） | 11.5904／62.9670 | 11.3561／62.2855 | 11.5283／62.5960 |
| 回放任务窗口（秒） | 1339.520 | 1306.640 | 1320.376 |
| P／D抢占 | 0／0 | 0／0 | 0／0 |

三档完整运行查询量均为6,977,618 token，实际输出28,416 token；所有请求输入输出长度匹配。P外部输入0、D本地输入计算0、D外部输入6,977,618。计数不累加TP重复指标，不将local compute当成GPU耗时、FLOPs或全部物理重算。

| 容量变化 | 命中增量 | local compute减少 | 后续TTFT P95改善 | 后续TTFT P50改善 |
|---|---:|---:|---:|---:|
| 12→24 GiB | +2.7296个百分点 | 190,464 token／26.7884% | 24.0424% | −3.7260% |
| 24→48 GiB | 0 | 0 | 0.5801%（23.04毫秒） | −1.7457% |

改善率定义为`(低容量值−高容量值)/低容量值`，负数表示较大容量本次更慢。E2E与完成时间也没有随容量严格单调改善。

可以把24–48 GiB描述为**本次观测中缓存计数已呈平台的区间**；不能证明精确拐点在24 GiB，真正变化位置可能在12–24之间，也不能推广为其他并发、长度或工作负载的饱和结论。每个有效容量仅一次观测，TTFT的小差异尚未经过重复验证；174请求不是174次独立系统重复。

![容量与命中率](results/capacity-hit-rate.png)

![容量与后续TTFT](results/capacity-ttft.png)

图中M1标为失败，M2为24 GiB有效点；旧H的编译干扰单列。仅展示实测点，不拟合曲线，不池化多次请求，不给没有重复实验依据的置信区间。TTFT面板纵轴尺度不同，已标注。

## M1保留，M2没有替换它

| 运行 | 结果 | 命中率 | 后续TTFT P50／P95 | 用途 |
|---|---|---:|---:|---|
| M1／3391，24 GiB | 160成功、1超时、13依赖跳过 | 92.1665%* | 0.5960／4.0256秒*，n=147 | 失败及覆盖差异记录 |
| M2／3406，24 GiB | 174/174成功 | 92.5400% | 0.6869／3.9716秒，n=161 | 主容量对照 |
| H／3343，48 GiB | 174/174成功；正式窗口42组TileLang编译区间 | 92.5400% | 0.6939／25.6893秒 | 历史延迟观察，缓存计数仍保留 |

`*` M1实际覆盖不同，成功样本的分位数和不完整窗口计数不等价于全负载结果，未作为主曲线点。M2不是从多个完整重跑中选出的较快一次：本阶段仅一次完整回放，且M2 P50高于M1成功样本P50。五次运行的全部指标见[summary.csv](results/summary.csv)，旧结果文件没有覆盖。

## 最小故障定位结论

M1源请求`5c7c6017-db96-4e9c-9b85-516c206fa824`为同一subagent第4轮，计划输入28,577、输出89。客户端在900.034秒后ReadTimeout，随后第5–17轮因上下文依赖失败而跳过。

这次审查补充了此前未展开的证据：

1. **P侧自身在等待ready。** M1 P.log第1269–1270行与D.log第467–468行，均指向内部ID`chatcmpl-0a60d905-3a63-4198-966a-0e2fa6e83c4e-b6439228`。读取实际安装的connector源码后确认：D元数据抵达P，P按transfer_id查找或创建发送状态并等待ready；超时后向D返回错误。ready在带block_ids的request_finished元数据路径中置位。因此不能直接把问题描述为“P已发送ready但D没收到”。
2. **Proxy→P HTTP层有异常候选。** M1 proxy-step.log记录`send_request_to_service`后台任务的`httpx.ReadError`，栈停在读取P响应头。Proxy并行启动P请求和D流，但只在D流结束后await该P任务，P异常可能没有及时向等待中的D链路传播。
3. **旧日志无法完成逐请求关联。** Replay没有发送X-Request-Id，Proxy随机生成UUID；旧日志没有seed/UUID映射，也没有该异常的明确时间戳。因而不能证明那条ReadError就是该客户端请求的直接根因，不能从聚合计数断言P具体prefill是否完成。

| 原三个问题 | M1现有证据能回答到哪里 |
|---|---|
| P是否完成该请求prefill？ | 无逐请求完成证据，未知。HTTP读错误是候选线索。 |
| KV传输是否启动／完成？ | D的connector请求已到达P并进入ready等待；该等待未正常完成。不能确认该请求的数据传输已完成。 |
| ready在哪一环失败？ | P发送状态的ready事件未按期置位；为何未置位尚未定位，不能声称只是D没收到信号。 |

源代码摘录在本阶段mooncake_connector.py（读取的安装版本）；相关流程在1252–1296、2001–2021行。没有升级运行时、修改connector、增大timeout或宣称修复了bug。

## 为什么跳过小复现，以及M2验证了什么

离线审查发现失败轮的纯上下文链只有4条，但首轮还有lead发送依赖。单独抽取会失去原并发、缓存竞争和Proxy HTTP连接复用历史，对当前HTTP错误候选的检验力有限；恢复这些历史需要新适配。因此按照用户已同意的例外，**在提交M2前记录决定：跳过小复现，用唯一一次完整负载检验复现性**。没有用完整trace充当额外预热。详见[DECISION.md](DECISION.md)。

为弥补旧日志映射缺失，M2只在Proxy增加少量阶段日志，记录seed、UUID、P开始/响应/错误、D响应头/首原始chunk/流结束，不记录prompt全文。174个计划seed唯一。没有改变请求体、headers、连接池、timeout、异常处理顺序或Replay逻辑。日志会带来少量额外开销，因此明确标记为观测性差异，不宣称执行文件逐字相同或性能完全隔离。

M2最终174条请求均可由seed唯一关联到Proxy UUID，174个P HTTP响应均为200、P HTTP错误0、D流结束174。上次失败轮在M2中：

- 输入28,577、输出89，全部符合计划；TTFT0.5875秒，E2E9.5938秒。
- Proxy UUID为`b0ba9566-c01f-406b-b633-afdbdff2c689`，P与D响应header中的ID均匹配。
- P HTTP往返约0.198秒，D流正常结束；该HTTP时间包含网络/排队/计算，不当作纯prefill时间。

原13条依赖后续本次也完成。M2正式窗口无相同ready或P HTTP读取错误、无TileLang编译开始记录，P仍有2条JIT监测告警，不能据此称完全没有编译。P105条周期传输汇总无非零错误，D没有独立同类周期汇总，记缺失；直接KV错误日志为0。

结论是**M1失败在这次完整负载重跑中没有复现**，可以保留为运行异常候选；一次通过不能证明系统稳定或排除确定性故障。缺失的M1逐请求证据无法由M2成功补造。请求关联表见[proxy-phases.csv](formal-3406/proxy-phases.csv)，汇总见[proxy-phase-summary.json](formal-3406/proxy-phase-summary.json)。D首原始chunk日志不替代客户端首有效token TTFT。

## 配置、有效性与清理

沿用同节点四张H20、P TP2＋D TP2、DeepSeek-V4-Flash、vLLM0.26.0、既有Mooncake与patch、eager、FP8 KV、上下文81920、MBT8192、P max_num_seqs=2、D=4。P24GiB、D48GiB；P APC开、D关。完整174条、并发3、seed0、同actor等待缩放0.1、adaptive构造及原输出长度不变。使用原两条预热→等待完成→P reset成功→formal-before→完整Replay→formal-after。

Replay计划与L完全一致，配置只差输出目录，P命令只差容量，D命令完全一致；M2与L使用同一组物理GPU，H2使用同节点另一组。客户端commit仍为`7f304555a8bc504c2c2257db2662e896eeeb5c30`，现有patch与归档cmp一致。三个完整session和token口径沿用上一阶段，完整说明见[上一阶段报告](../stage-v2/REPORT.md)。未保存所有实际prompt token，不声称闭环生成内容逐token一致。

M2所有174请求校准准确、输入输出长度匹配、无reset、无失败/超时/跳过/抢占；结束P/D running/waiting均0。阶段均值按正式窗口sum/count差分：P queue0.2325秒、P prefill0.7122秒、D queue1.0992秒、D prefill0.2063秒、D decode16.5434秒，每项n=174。详细差分与五次阶段表在results/stage-means.csv，不加减阶段分位数或推断队列峰值。

SLURM3406为COMPLETED0:0，作业耗时29分23秒。P/D/controller剩余列表空、实际tracked PID已无、本轮GPU应用空、服务端口已释放、IPC不变、本轮映射shm已消失。新增6个shm对象和变化的监听进程通过inode/maps/cgroup归属到其他Qwen作业3398，未触碰；原有root dmesg僵尸为基线，退出快照的另一个root临时sh僵尸在一次复查时已不存在。无GPU的只读归属检查作业3407亦已退出，限时2分钟、1CPU/1GiB。

退出可用内存约1.99TB、存储余量4.9TB、192CPU上的load1为6.32，无本轮健康回退。共享节点背景作业在本轮后段由3393变为3398，无法视为恒定背景负载，性能结论保留此限制。

## 命令与交付

已执行一次正式提交（仅记录，不要重复提交）：

```sh
sbatch --export=ALL,CAPACITY_LABEL=M2,P_KV_BYTES=25769803776,D_KV_BYTES=51539607552 /home/david_cwq/zhouziheng/agent-replay-20260917/evidence/pd-capacity-20260919/stage-v3/pd_m2.slurm
```

新台账formal-runs.jsonl恰一条M2；旧四次台账保持不变。本阶段无独立小复现、无额外完整回放、无故障修复重试。离线分析和单次正式复现均已完成，当前不需要追加研究。

本地重建统计（项目根目录）：

```sh
python3 scripts/summarize_point.py stage-v3/formal-3406 evidence/selected-trace.jsonl M2
python3 stage-v3/supplement_run.py stage-v3/formal-3406 M2
python3 stage-v3/join_proxy_phases.py stage-v3/formal-3406
MPLCONFIGDIR=/tmp/pd-capacity-mpl python3 stage-v3/build_results.py
```

报告、五运行summary.csv、两图、容量增量表、原始M2证据、Proxy链路表、源码/协议修改和清理证据都保存在stage-v3。远端对应目录为`/home/david_cwq/zhouziheng/agent-replay-20260917/evidence/pd-capacity-20260919/stage-v3`；旧原始材料继续复用。失败M1、历史H及前阶段报告均完整保留。
