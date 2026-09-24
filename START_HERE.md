# KVLab：CLI 与 Agent 使用

本轮交付以CLI、JSON/JSONL和请求/事件证据为主，不依赖HTML。后端为锁定的H20 DeepSeek-V4 TP2五组原生Scheduler/缓存管理；仅研究实际前缀采用、原生查询命中率和累计本地输入处理，不预测TTFT/吞吐，也不支持把H20配置改名当成Ascend。

## 环境与输入入口

后处理与当前native单元回归使用Python 3.10+及标准库，不需要vLLM。原生执行需要现有带项目补丁的vLLM 0.26.0 CPU环境，设置KVLAB_PYTHON指向该环境Python；普通同版本发行包不保证等价。本轮不重新安装引擎，不运行模型或申请GPU。服务器操作须遵守操作者的server-health/h20-slurm说明，只在SLURM计算节点执行。

输入均在 `kvsim/tests/fixtures/native/`，这些同时是可复制修改的小样例和测试资产：

| 输入 | 内容 |
|---|---|
| history-small-workload.json | 人工synthetic的A→B→A，3请求；按ClientComplete依次发送 |
| exact-history-conditions.json | 1P，字节预算467856017（450块、17字节余量）与块数预算1200 |
| parallel-workload.json | 4独立请求，既有机制样例，非实机捕获 |
| parallel-route.json / two-p-conditions.json | 2独立P的冻结落点与调度条件 |
| history / active / two_p | 原生小结果，分别展示前缀收益、零收益和多P；原始计数保持不变 |

默认预算来源assumed，不冒充实机AFD/baseline。多个P不是共享池，TP rank不是P。每个P同预算；当前不支持逐P异构配置。源码和环境证据沿用上版提供的锁定运行时；运行会记录实际加载原生源码与有效配置。

workload的schema为kvlab-replay-workload/v1。metadata声明content_source、execution_profile；requests按稳定候选顺序排列，包含唯一runtime_request_id、runtime_session_id、actor_id、source_key、node_type=request、完整tokens、等于数组长度的input_tokens、原始output_tokens、send_after、context_after、effective_interval_seconds和一致的content_source。依赖必须指向之前的请求，后继内容已经冻结，不由模拟器临时生成。cache_identity仅支持空字符串；当前逻辑协议不把秒间隔换成调度步。captured_tokens还需tokenizer_sha256与prompt_template来源。

conditions的schema为kvlab-native-conditions/v1。直接复制样例更改：client_max_in_flight为全局在途上限，p_max_num_seqs为每P序列上限，p_max_num_batched_tokens为每P批次token预算；p_domains为P缓存域数。三个并发参数必须为正整数，不会静默调低。

capacity_points与旧capacities_gib二选一；每点提供唯一id、authority及bytes_per_rank或physical_blocks。物理块包含一个null保留块。两个预算字段同时给出时核对floor换算一致，允许字节余量。块数权威且未给字节时字节预算为null。不同字节映射同一块数合法，比较标注有效容量未变化。最多8点，每P预算不超过锁定布局48GiB对应块数，合计物理池不超过100000块。

routing使用kvlab-native-routing/v1，覆盖全部request→P并绑定workload摘要。生成器为确定性actor亲和，不是实机路由；真实逐请求落点需明确来源。trace路由路径相对conditions文件解析。换workload后必须生成或导入匹配的路由。

## 校验、执行和后处理

在解压包根目录运行：

```sh
python3 -m kvsim.native.inputs kvsim/tests/fixtures/native/history-small-workload.json
python3 -m kvsim.native.conditions kvsim/tests/fixtures/native/exact-history-conditions.json
```

在已配置原生CPU环境的H20共享目录中，从解压包根目录提交；KVLAB_PYTHON由操作者设置，KVLAB_SOURCE_ROOT指向本包。输出必须是新的空目录：

```sh
export KVLAB_SOURCE_ROOT="$PWD"
sbatch --parsable --output=history-%j.log kvsim/native/jobs/run_native.slurm \
  "$PWD/kvsim/tests/fixtures/native/history-small-workload.json" \
  "$PWD/my-history" \
  "$PWD/kvsim/tests/fixtures/native/exact-history-conditions.json" "$PWD"
```

作业4CPU、16GiB、20分钟，无GPU，进程15分钟上限；PYTHONHASHSEED固定为0。查调度器终态和每点summary，不能只看提交成功。已有授权D/Z观察规则保留；不得改动其他作业或服务。

本地后处理可直接使用新输出，也可复制已有原始结果重分析；后二者须在报告中区分。以下针对my-history：

```sh
python3 -m kvsim.native.compare my-history
python3 -m kvsim.native.prefix_evidence my-history kvsim/tests/fixtures/native/history-small-workload.json
python3 -m kvsim.native.contrast my-history/low my-history/high my-history --mode capacity-only
python3 -m kvsim.native.bundle my-history my-history/native-results.json
```

三种比较：capacity-only固定机制、负载、P、路由、调度和协议，仅预算可不同；single-variable一次改client_max_in_flight、p_max_num_seqs、p_max_num_batched_tokens或routing；deployment-conditional允许明确声明的预算、拓扑、路由和上述调度条件联合变化。所有模式拒绝源码及固定缓存规则差异，部署联合差异不能全部归因显存。

## Agent 使用

按“选择输入→冻结条件→校验→执行→核验→解释”顺序工作。可以编辑配置、构造格式合法的小负载；日常实验不修改模拟核心，不写替代计数脚本，不建设Agent服务。

1. 明确用户要固定和改变的条件。优先复用有来源的默认值并列明；会改变实验含义且无法判断的缺项再确认。真实预算缺失时明确假设，不静默换profile、改容量、缩并发或寻找正收益。
2. 将配置和输入放入独立实验目录，记录来源。执行校验后运行一次有界实验，不覆盖已有结果，不因观察超时重投仍存活的作业。
3. 先读scan、manifest、summary；只有完整且可比才报告全量ΔC。调用compare/contrast与prefix_evidence作确定性汇总，再按需读取首差请求和事件。
4. 输出“实际条件与假设→主指标及差值→关键请求证据→结论边界→配置和结果位置”。数字必须来自工具文件；无差异是合法结果，不可比不是零收益。

建议演练任务：“使用随包A→B→A负载，在当前支持的profile下，只比较样例450/1200块两档KV预算。运行新实验，报告实际采用比例、原生查询命中率、local-compute与首差证据，并说明假设。”随后读取active旧结果报告零收益，再尝试一个不支持的profile，解释拒绝原因，不擅自改参数。

## 状态、退出码和证据入口

inputs/conditions成功输出JSON且退出0；routing将JSON写到指定文件；run逐点输出summary，任何未完成点最终非零退出。compare、contrast、prefix_evidence、bundle成功退出0并写对应文件。非法输入、不可比和校验失败为非零退出，原因在stderr；第三方日志不要求JSON化。已有旧文件不能作为此次成功的依据。

| 文件 | 关键信息 |
|---|---|
| scan.json | 运行点列表；数字旧点目录为Ngib，字符串点目录为id |
| manifest.json | run_id、workload摘要、路由、条件、预算来源、原生源码和有效profile |
| summary.json | status、完成/计划数、全局/per_p指标、失败原因、观测边界 |
| requests.jsonl | request_id、P、输入摘要、采用和处理量、成功输入区间、生命周期 |
| steps.jsonl / events.jsonl | 该run自己的逻辑步、P、调度、物理块和相关缓存/生命周期事件 |
| comparison.json / contrast.json | 比较身份、有效变化、首差或ΔC；两侧必须是实际run |
| first-difference-evidence.json | workload、比较对、run/P/request与输入摘要绑定的前缀事件 |
| native-results.json | 可选汇集文件，程序可直接读取，不依赖HTML |

采用比例与原生查询命中率不同；比例由分子/分母聚合，零分母为null。local-compute统计成功完成的本地输入区间，含同请求实际重复处理，不计内部握手。重复处理不能仅凭公式归因抢占。等待队列采样不自动等于容量阻塞；释放引用不等于驱逐，Removed条目不等于物理块数。

incomplete保留已完成工作和失败状态，禁止混入完整负载收益。只有最后部分轮次可缺P；已完成P的处理量保留，未观测P不补零。observation_boundary单列末轮观测，peak_active_blocks_global仅来自完整观测轮次，尚无完整轮次时为null。中间缺行或损坏仍拒绝。

comparison/evidence和contrast双方必须绑定实际run。旧元数据不足时不能附加组合；原始run身份足够但后处理文件过旧时，重新执行compare→prefix_evidence→contrast→bundle，不修改原始计数。不要把A/B的数字和C/B的事件拼接。默认先读摘要，按run→P→request输入摘要→该请求自身step→事件追溯，不能按跨run同号step强行对齐。

## 独立包测试

必需的当前native回归无需原生环境，所有fixture随包：

```sh
python3 -m unittest discover -s kvsim/tests -p 'test_native*.py' -v
```

Replay导出是独立依赖边界：Python3.12及requirements-export.txt中的pydantic/httpx/PyYAML/tokenizers，Replay源码随包位于stage-v4/source/client，测试配置和两请求trace在tests/fixtures/replay。使用安装好依赖的Python执行：

```sh
python -m unittest kvsim.tests.test_replay_export -v
```

历史浏览器/旧内核测试不属于本次CLI交付测试入口，不需要为其补入旧工作区。必需fixture缺失应直接失败，不能用skip掩盖。原生异常路径测试native_partial_round.py需锁定CPU环境，在SLURM内运行；它只在测试内注入p1异常，不增加生产驱动故障开关。
