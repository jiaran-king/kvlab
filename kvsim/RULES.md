# KVSim 0.1：规则、来源与适用范围

本工具计算固定逻辑事件交错下的缓存机制结果；不执行模型，不预测秒数、FLOPs、真实显存峰值或真实硬件可部署性。它不是线上 scheduler 的逐行复刻。

## 冻结预设

- Ascend：`3281a5fc44ec344ba304c9161a3959d8649471f4`。关键源码由官方仓库的该 SHA 获取，保存在 `source/ascend/`。
- vLLM：本机 `vllm-v0.26.0` checkout，HEAD `568afb3a13806beb53bb2e6bd518269357b237c0`。使用文件无工作区修改；副本在 `source/vllm/`。
- 模型形状：已有 Flash config，43 层（21 C4、20 C128、43 SWA），head_dim=512，index_head_dim=128。最后的 MTP 配置条目不启用。
- A3：BF16 MLA/SWA，int8 indexer + FP16 scale，FP32 compressor state；TP4，CP=1、MTP 关闭。连续位置状态页路径，不包含新私有 ring/checkpoint patch。
- 这是明确冻结的**源码推导预设**。尚未取得 Ascend 历史部署实际 vLLM SHA、完整本地补丁和有效 cache 配置快照，不能称为那台历史部署的逐字认证副本。此差异是历史验证边界，不用猜测补丁填补。

## 源码到实现

| 规则 | 冻结源码位置 | 模拟实现 / 检查 |
|---|---|---|
| A3 block 表 | `ascend/.../models/layer/attention/layer.py` 的 `get_dsv4_block_sizes` | `profile.resolve`；AST 提取表逐项比较 |
| MLA/indexer/SWA/state 的字节与窗口 | `ascend/.../models/deepseek_v4.py` 的三个 Cache 类、`Compressor`；`core/kv_cache_interface.py` | `profile.resolve`，不乘 TP 形成逻辑总池 |
| shared physical ID 布局 | `patch_kv_cache_utils.py` 的 `group_and_unify_kv_cache_specs`、`_get_kv_cache_groups_uniform_groups`、`_get_kv_cache_config_deepseek_v4` | 21/20/43/21/20 layer tuples，padding 选择22 |
| 压缩 KV 分配和命中 | `core/single_type_kv_cache_manager.py` 的 `CompressAttentionManager` | raw progress 先除 ratio 再 ceil；dense 从左向右查找 |
| 混合恢复 | `patch_kv_cache_coordinator.py` 的 `find_longest_cache_hit` | 共同候选单调收缩，窗口缩短后重新检查各组 |
| SWA/状态窗口、retention | `vllm/.../single_type_kv_cache_manager.py` 的 `SlidingWindowManager` | 需要 ceil((window-1)/block) 连续尾块；AST 执行原 retention mask 与本实现比较 |
| 引用与替换 | `vllm/.../block_pool.py` 的 allocate/touch/free/cache 路径 | `Pool` 独立物理页、重复键多页、触碰移出 free 队列、反向释放 |
| 完整输入准入 | vLLM `KVCacheManager.allocate_slots` / manager admission cap | `engine` full-input gate；watermark=0；无抢占及额外预留 |
| logits 末位置 | vLLM `KVCacheManager.get_computed_blocks` | 最大命中为 P 输入长度减1，再按合法恢复边界查找 |

这里的 `...` 分别表示 `source/ascend/vllm_ascend/` 或 `source/vllm/vllm/`。

### 物理池

CLI block B∈{32,64,128}：

- C4 KV/indexer：原始 token block = 4B。
- C128 KV：原始 token block = 128B。
- SWA：block=B，window=128，两个 layer 子组（22/21）。
- C4 KV/index state：block=B/16，window=8。
- C128 state：block=B/4，window=128。

上述6组竞争同一个 block ID 池。物理 ID 在每 rank 占 `22 × B × (1024+130)` 字节，池容量是 KV 字节预算整除该值；ID 0 是保留 null block。TP ranks 是同一逻辑域的布局，不将 rank 容量直接相加。

首版支持组合 retention=128B、共同恢复边界=128B；hash 基础粒度=B/16。retention 与共同对齐一致时，额外 reachable-boundary tails 是这些边界的子集。模拟器使用完整前缀内容身份，而不复刻特定哈希库的二进制编码；假设无哈希碰撞。

### 输入

统一内容是一列 `(content_id,start,length)` 切片。相邻连续切片归一化；边界 hash 覆盖整个前文及 `cache_identity`，不是只看当前片段名字。实际 token 被表示成稳定的 token-ID 单位内容。内容片段 ID 是用户声明的内容身份，不能用相同 ID 表示不同内容。

`send_after` 约束执行，`context_after` 描述内容来源；缓存引擎只看规范化后的明确内容。不根据 session 推断相等。不同 session 可以共享相同内容。同域、相同 cache_identity 才能复用。

### 执行规则

生成器按输入列表确定性选取可执行请求；HTTP 并发、每 P 执行槽分别限制；每 tick 每 P 共享 token budget。每次 SCHEDULE 后紧接 STEP_COMPLETE，再处理下一请求，保证无未提交状态被使用。分块目标按冷请求进度生成，容量扫描复用同一份事件。命中超过当前冷目标的部分会跳过计算，后续目标追上后才计算新增输入。

实际 vLLM 可提前登记 hash 并由执行流依赖保证安全；本生成规则序列化每个 step，故状态在 STEP_COMPLETE 才可查。显式事件允许未完成分配存在，但不允许在途内容复用；这是本工具支持的执行假设，不声称复刻异步调度的全部顺序。

在下一次分配前，按已提交位置反向释放窗口外引用。已完整计算且落在 retention 尾部的页注册前缀索引，其余页仍可被运行中请求持有。P input 完成后保留最后引用至 P_RELEASE。D 输出仅进入后继输入内容，不在 P 缓存中自动发布。

默认 transfer_ticks=1、decode_ticks=2 是虚拟顺序参数，与输出长度的硬件耗时无关。原始输出长度保留，影响后继输入。没有 D 时延模型。

准入检查使用 full_sequence_must_fit、recycling-aware window caps、watermark=0；资源不足停止该配置。支持范围不含非零 watermark、其他请求的 scheduler reservation、抢占、MTP、DCP/PCP、部分块 CoW、外部 KV、异步取消或 CACHE_RESET 事件。冷起点固定。非法、未支持及轨迹不可行必须明确返回。

### 计数

P_i 为本场景明确给定的 P 输入范围（默认完整输入）；H_i 为成功准入采用量；C_i 为完成步骤累计计算量。完成请求检查 C_i+H_i=P_i。历史实验可能有 P/D 边界差异，本工具不擅自补减425 token。

输入缓存占比=ΣH/ΣP，仅汇总完成请求。部分运行单列。没有模拟运行时额外查询计数，因此不提供同名 query-hit 指标。

解释保存当时查询的边界与最近物理替换证据。证据只解释模拟状态，不证明历史运行唯一因果。解释页面不再调用 lookup。

## 425 资产完整性

来源：`output/ascend-handoff/Ascend910C_KV_Replay_425/workload/reference-plan.json`，AgentInfer `7f304555…` 安装源码及实验补丁对应计划。

已具备：425节点、6 session、send/context依赖、计划输入13,707,996、计划输出70,195、context mode。默认适配器按前驱输入+合成输出构造，再按目标长度做前缀切片/补新内容。这不是历史 PromptBuilder 的实际 trim，也不是原始对话逐字重放。

尚缺：Ascend 最终 P token 数组、逐 chunk 与传输释放事件、完整有效布局、本地补丁。历史 H20 数据不能拿来数值验收本 Ascend 预设。425 结果明确是“历史结构＋合成内容＋虚拟事件”。有捕获 tokens 时可通过 `workload=agentinfer` 的 captures 映射输入，事件可显式传入。

历史结果只能传给 `result.compare_observed`，其字段不进入 engine。源代码规则测试与手算用例负责核心验收；严格历史逐请求验证仍受资产缺口限制。

### 可选的部署输入上限

`config.max_input_tokens` 为正整数或 null/省略，约束 P 输入，不包含本轮 D 输出。未设置不额外限制输入长度，也不宣称真实模型可支持无限上下文。窗口准入上界使用 `ceil(min(window-1+step_budget, configured_limit)/block)+1`；省略上限时使用 `window-1+step_budget`，最终仍与请求自身所需块数取小值。原先写死的 81920 已移除。资源保护（请求数、累计输入、事件数、计算时间）属于工具限制，不属于模型或部署能力。
