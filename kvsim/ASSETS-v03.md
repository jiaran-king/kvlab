# v0.3 资产核对（进行中）

- 完整目标：GOAL-v03.md。当前 goal 活跃，本文不是完成声明。
- 缓存规则冻结文件：source/vllm，版本 568afb3a13806beb53bb2e6bd518269357b237c0；source/ascend，版本 3281a5fc44ec344ba304c9161a3959d8649471f4。TP4 A3 continuous-state 预设，未证明与历史容器所有额外补丁等价。
- Replay 本地代码：../stage-v4/source/client/agentbench/replay；另有 Ascend 交接包 vendor/agentinfer。对应历史基线 7f304555…，具体源码/补丁关系须继续核对，不能将两个目录视为相同版本。
- 已有输入：stage-v4/successful-425-trace.jsonl，formal-3429/replay-config.json 和 replay/replay-plan.json；交接包 workload/reference-plan.json。
- 已有部分内容资产：formal-3429/prompt-samples.jsonl、cold-tokenized.json、continuation-tokenized.json。完整覆盖度尚待核对。
- tokenizer：交接包 reference/model-metadata 有 tokenizer_config.json，model_max_length=1048576；当前定向检索未找到完整 tokenizer.json。配置本身不能替代分词词表和渲染模板。不能据此声称离线完整导出已可行。
- Replay TokenizerClient 当前通过 HTTP 做 count/tokenize/render，需离线适配；不启动模型服务作为替代。

## 已完成的核心修正

释放无 hash 块按批次前插，有 hash 块尾插，批次内顺序保持。未使用物理 ID 采用惰性区间表示，位于释放无 hash 块之后、有 hash 空闲块之前。每个缓存组保持与上游对应的批量释放。

独立验证：tests/test_source_pool.py 直接 AST 提取冻结 FreeKVCacheBlockQueue 整类，以及 BlockPool 的 get_new_blocks/free_blocks/touch/get_num_free_blocks。块存储及 eviction 回调为替身；因此此测试证明队列和引用行为，不能宣称完整上游 hash 索引验证。400 次固定种子候选操作与 Python、JS 池对照；另有手工批量顺序案例。20 项现有测试通过，详见 ../output/kvsim/v03/tests.txt。

旧竞争案例修正后19个容量点（8、12至16每0.25、24 GiB）全部28/28完成、采用196608、计算418688、采用比例31.9534%、有效缓存替换0。详见 ../output/kvsim/v03/reclaim-correction.json。旧台阶不再是可信容量收益证据。

## 仍需完成

其余独立源码验证、Replay资产完整核对、schema/exporter/importer、双执行模式、诊断和UI、完整回归验收，均按 GOAL-v03.md 继续执行。

## 第二阶段进展

实际复用 stage-v4/source/client 的 analyzer / planner / sampler，读取 successful-425-trace 和 formal-3429 配置后得到6会话425请求。规划器正常返回 calibration pending；exporter 在离线构造阶段调用 PromptBuilder 完成校准，不把结构 plan 的 execution_ready=false 当作不可导出。

新增 replay_export.py、WORKLOAD.md、严格 workload validator/import inspector。新增负载驱动事件生成器，复用现有事件处理与缓存核心；等待按 ceil(seconds/seconds_per_tick) 转换，session concurrency 和全局在途请求/P活动槽分开。输出阶段使用 decode_ticks+ceil(output_tokens/decode_tokens_per_tick) 的显式近似。每个处理步在本 tick 提交，传输释放最早在下一 tick；即使 transfer_ticks=0 也不在提交阶段内释放。零时长 timing-only 节点可以同 tick 完成。

验证：24项 Python 测试全部通过（使用 kvsim/.venv/bin/python），含2条源码队列对照、4条Replay导出/规划测试；workload_core.cjs验证等待换算、会话名额、timing-only节点、命中后单步5920 token、取消、无静默回退及确定性。导出测试注入的425输入为测试token，仅证明runtime绑定，不是历史内容capture。另一份两请求trace与3次会话采样已验证身份与计划确定性。

HTML已接入两种导入、执行模式及显式虚拟时间参数。浏览器交互仍未验收。完整tokenizer未发现；已询问用户本地路径，未因此停止独立工作。仅找到12条prompt sample及两份tokenization输出；不足以全量capture导出。完整425内容构造、真实capture与渲染校验、其他缓存机制源码对照、诊断展示和最终全流程验收仍待完成。

## 第三阶段：资产缺口已解决及独立验收

从官方 deepseek-ai/DeepSeek-V4-Flash 固定 revision 60d8d70770c6776ff598c94bb586a859a38244f1 取得6.4MB tokenizer.json，仅下载tokenizer/config，无权重。下载记录、文件摘要、前后本机资源状态在 output/kvsim/v03/tokenizer。tokenizer_config与历史metadata逐字一致。纯文本content parts采用冻结chat_utils的非空过滤和换行连接后，6首轮+1续接与历史prompt-check-samples中的服务端tokens逐个完全一致。早先cold-tokenized/continuation-tokenized是独立容量冒烟输入，不能拿它们与12条运行prompt-samples误配。

完整425已经通过原PromptBuilder导出；固定append/trim/subagent_first/lead_resume/independent共5分支与13个祖先直接重构一致。另导出独立小trace、seed17、3次会话采样，共15请求，重复采样私有内容不同。实际token数组保留，不展开成逐token片段对象；前缀按固定128token块的SHA256链计算，另以Node crypto验证内容/切片/隔离；每次模拟使用独立缓存，输入变化不会沿用旧摘要。

核实16个Replay源文件与交接包vendor逐字一致。正式3429入口额外加载request_admission.py，不在ReplayExecutor类自身代码内：所有6session同时启动、全局HTTP请求并发3。exporter现在显式支持upstream-session/request-admission两种metadata执行配置，并要求后者提供补丁来源。此前按session并发3生成的workload保留为另一个配置，不能称为历史并发语义。

新增真实425 request-admission workload及扫描：8GiB在82请求后准入失败；12/16/24完整，采用9355264、计算4352732、比例68.2468%。每点使用同一token集合与路由；不是实机延迟预测。结果见request-admission-sweep.log与acceptance.json。

剩余状态以AUDIT-v03.md为准；前文的“tokenizer缺失”等是当时进展，不是当前阻塞。
