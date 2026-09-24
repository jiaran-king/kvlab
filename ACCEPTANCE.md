# KVLab 可靠性收尾与 Agent 直接使用：验收报告

日期：2026-09-24。范围以本包GOAL.md为准，HTML暂缓，不新增Agent平台或硬件后端。

**F1–F5修复回归通过；独立Agent原生端到端演练通过。** 这不代表真实AFD/baseline部署或Ascend后端已验证。

## 修复与证据

| 项目 | 实现与验收 |
|---|---|
| F1 部署对照机制漏检 | semantics.validate_mechanism_pair由compare/contrast复用，检查原生源码、固定effective规则及调度声明。所有模式拒绝源码/retention变化；合法seqs、MBT和拓扑联合变化通过。deployment仅放行受支持的部署变量。 |
| F2 基线和证据错配 | comparison记录workload与point→run绑定；evidence核对实际摘要和请求；bundle核对comparison、evidence、contrast双方的run/P/请求身份，并复用contrast核验缓存文件与实际双方。错误基线、错run、错比较对、旧contrast绕过新机制检查均拒绝；正确组合通过。 |
| F3 多P半轮中断 | 步骤在实际逻辑完成和输入记账后落盘，失败批次不记处理量。仅允许incomplete末轮为P顺序前缀，中间缺行/乱序/缺失字段仍拒绝。observation_boundary列出已观测/未观测P；全局峰值只取完整轮次，无完整轮次时为null。 |
| F4 比率公式 | 全局和各P采用比例、query hit率按分子/分母核验，检查非负整数计数、零分母NA、有限值和浮点容差。错误75%、NaN/Infinity与错误NA被拒绝；零命中、空P与partial合法NA通过。 |
| F5 可移植测试 | 当前native测试全部使用约1.2MiB随包小型原生fixture。Replay测试改为随包两请求trace和配置，不依赖旧425配置。旧UI/旧内核测试明确不属于本次CLI测试入口；报告不再硬编码旧h20-conditions-events.json。 |

对应反例和合法正例在kvsim/tests/test_native_reliability.py；正常输入/预算/路由/账本等回归在test_native*.py。未新建通用校验框架或第二套计数器。compare/contrast/bundle等CLI结束时输出状态和结果路径，不要求第三方日志全部JSON化。

## 原生异常路径

最终异常验证为SLURM **3972，COMPLETED/0:0，25秒**，CPU4、16GiB、20分钟，无GPU。测试只在测试脚本内对p1 schedule注入异常，不增加生产故障开关。

validation/fault-round-final包含同一小负载的两个完整点和一个真实半轮失败点：

- complete-a与complete-b均完成4请求，各处理4096 token，仍可比较且无首差。
- partial在p0真实完成后、p1开始前失败，保留768 token；p1处理量0但没有伪造p1步骤行。
- 末轮已观测p0，未观测p1，活跃块部分观测和315；尚无完整轮次，全局完整轮次峰值为null。

原生原始requests/steps/events及fault-validation.json、fault-3972.log和scheduler-3972.txt随包。早期3970验证后将无完整轮次的峰值从初始0修正为NA，最终复跑以3972为准。输入计数未变化。

## 独立 Agent 演练

以不携带本任务长对话的独立Agent执行，只提供干净解压包、自然语言任务及已授权运行环境。Agent从START_HERE开始，未修改核心或重新实现计数算法；无需额外人工指导。详见trial/AGENT_TRIAL.md及commands.jsonl、CLI日志。

新实验为 **3971，COMPLETED/0:0，26秒**，3请求A→B→A、1P、固定路由和调度，仅改变KV预算：

| 点 | run_id | 完成 | 实际采用率 | 原生查询命中率 | local-compute |
|---|---|---|---|---|---:|
| low：450块 | native-54c95786ad23f84d4535 | 3/3 | 0/3072=0% | 0/3072=0% | 3072 |
| high：1200块 | native-0f7020e3f12468b20396 | 3/3 | 768/3072=25% | 768/3072=25% | 2304 |

差值768 token（25%）；首差history-2在low处理[0,1024)，high处理[768,1024)。请求摘要、p0、各run自身step及相关存储/移除事件均可追溯。采用率与查询率定义不同，本例恰好相同。

Agent还重分析active旧结果，正确报告两项指标无收益、local-compute均4096，不把重分析称为新执行；对不支持的Ascend profile得到exit1和unsupported native cache profile，未擅自替换条件。

演练使用预先配置的锁定vLLM CPU运行时及SSH/SLURM权限，不证明全新机器环境安装。作业日志保留内存、存储、端口/IPC采样、GPU检查和调度终态，未改动其他作业或服务。端口/IPC采样不冒称全主机穷尽审计。D/Z沿用已授权日志观察规则。

## 最终包验证与正常数字

必需测试命令：

- python3 -m unittest discover -s kvsim/tests -p 'test_native*.py' -v：**41项全部通过，无跳过**。
- 使用具备requirements-export.txt依赖的Python3.12运行python -m unittest kvsim.tests.test_replay_export -v：**4项全部通过，无跳过**。

日志位于validation/native-tests.txt、validation/replay-tests.txt；最终解压包复验记录位于validation/clean-package-tests.txt。未靠纳入庞大旧工作区解决测试缺失。

history、active、two_p正常后处理链路已重建；历史竞争处理3072/2304、active处理4096/4096、two_p处理4096均保持。原始输入、采用量及local-compute未改写。只新增身份绑定、观测边界、严格校验和状态/路径输出。

独立演练结束后，主代理补充了空/损坏步骤拒绝、bundle对缓存contrast的复核及CLI状态/路径输出。这些为后处理/输出校验；原生场景与计数不变。最终代码重新执行了trial的新运行与active后处理及全部指定测试，没有把这一复核冒充第二次独立Agent演练。

## 验证边界与停止

预算仍为assumed，后端为H20 TP2五组缓存。缺少真实AFD/non-AFD有效KV账本、目标缓存机制及逐请求路由的联合证据，真实AFD收益与Ascend适配仍未验证。TTFT/吞吐不在本轮范围。

本轮没有剩余必需修复或演练阻塞。HTML继续暂缓；不增加实验矩阵、Agent服务、自然语言解析器或项目内LLM调用。
