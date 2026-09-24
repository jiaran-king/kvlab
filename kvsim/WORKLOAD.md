# Replay workload v1（v0.3 实现进行中）

工作负载 schema 为 `kvlab-replay-workload/v1`，不同于完整 scenario 的 `schema_version: 1`。

metadata：exporter_version、source_trace、source_sha256、agentinfer_commit、source_modules、planner_version、replay_config、seed、model、tokenizer_sha256、prompt_template、content_source、time_unit=seconds、session_concurrency、sessions、assumptions。sessions 项为 id、launch_order、arrival_seconds。

request 节点：runtime_request_id、runtime_session_id、source_key、actor_id、actor_role、node_type=request、tokens（最终完整有序 token IDs）、input_tokens、output_tokens、cache_identity、content_source、send_after/context_after（完整 runtime request ID 或 null）、context_mode、effective_interval_seconds。

timing_dependency 节点不占 P 内存，没有输入 token，保留 send_after、effective_interval_seconds、effective_duration_seconds；不能作为上下文父节点。

内容模式为 captured_tokens 或 trace_driven_synthetic。前者必须来自 runtime request ID 对应的完整 capture；后者经原 PromptBuilder 构造，以命名空间确定的输出替身延续上下文。它不是历史实机精确回放。

## exporter

Python 3.12，依赖原 Replay 需要的 pydantic 2、httpx、PyYAML 及 tokenizers。httpx 只供原模块导入，离线适配不构造 HTTP 客户端。源码入口显式指定，使用原 analyzer/planner（内部调用 sampler）与 PromptBuilder。

```bash
kvsim/.venv/bin/python -m kvsim.replay_export \
 --agentinfer-source stage-v4/source/client \
 --agentinfer-commit 7f304555a8bc504c2c2257db2662e896eeeb5c30 \
 --trace stage-v4/successful-425-trace.jsonl \
 --config stage-v4/formal-3429/replay-config.json \
 --tokenizer /path/to/complete/tokenizer.json \
 --output output/kvsim/replay-workload.json
```

或使用 `--captures capture.json` 替换 `--tokenizer`。capture 格式为 `{"schema":"kvlab-token-capture/v1","metadata":{"tokenizer_sha256":"...","prompt_template":"..."},"inputs":{"runtime-request-id":{"tokens":[1,2],"output_tokens":3,"cache_identity":""}}}`。缺少任何实际请求的输入时失败，不补片段。

目前离线渲染适配范围：冻结 vLLM DeepSeek-V4 chat/completions 默认 chat 模式、纯文本及其工具定义；其他端点不能套用该模板。渲染函数复用 source/vllm/vllm/tokenizers/deepseek_v4_encoding.py。仍须与已有实际 capture 核对，不能仅凭本地可执行声称与实际部署一致。

测试 fixture 的注入 token 仅验证绑定和格式，不作为历史输入证据。完整425内容导出仍缺少本地完整tokenizer或全量capture；schema、双执行模式和网页接入已有初版与单元验证；浏览器交互及完整内容链路未验收，不以本文件代表完成。


## 执行模式

Replay workload 默认 `execution_mode=workload`。秒等待按 `ceil(seconds / seconds_per_tick)` 转换（默认1），同 tick 先释放传输引用、完成D、完成timing节点、释放会话名额、启动会话、就绪请求、按稳定请求顺序调度。会话启动按 launch_order，根请求等待相对于会话实际启动；其他请求等待相对于 send_after 完成，并另行满足 context_after 完成。

每步实际计算共享 P 的 step_budget，首次查找后从 adopted token 开始。P计算提交后传输引用最早下一tick释放，延迟为max(1,transfer_ticks)；D完成在释放后 decode_ticks + ceil(output_tokens/decode_tokens_per_tick)，默认额外2步和256token/步。这是声明的排序近似，不是设备吞吐。timing节点只占会话生命周期、不占P输入槽或全局在途请求数。

固定模式继续解释明确的事件流，不会自动把带等待的Replay workload转换成忽略等待的冷轨迹；选择固定模式但未提供事件时明确拒绝。负载模式的结果另外保存 executed_events 和 session_launches。

## 已验证的实际导出命令与并发补丁

本地完整tokenizer现位于 `output/kvsim/v03/tokenizer/tokenizer.json`，来源为官方仓库固定revision，7个历史服务端token序列匹配证据在同目录。以下为历史3429的请求准入补丁语义：

```bash
kvsim/.venv/bin/python -m kvsim.replay_export \
 --agentinfer-source stage-v4/source/client \
 --agentinfer-commit 7f304555a8bc504c2c2257db2662e896eeeb5c30 \
 --trace stage-v4/successful-425-trace.jsonl \
 --config stage-v4/formal-3429/replay-config.json \
 --tokenizer output/kvsim/v03/tokenizer/tokenizer.json \
 --execution-profile request-admission \
 --admission-patch stage-v4/formal-3429/code/request_admission.py \
 --output output/kvsim/v03/replay425-request-admission-workload.json
```

不传execution-profile默认upstream-session（原ReplayExecutor的会话并发语义），全局在途上限默认工具节点上限2000；request-admission让所有会话进入、用Replay max_concurrency限制在途请求。两者都不运行HTTP executor，metadata记录选择及补丁摘要；KVLab可显式覆盖执行参数，结果快照记录覆盖后的配置。稳定虚拟调度不模拟真实HTTP竞态或Prompt构造用时。

实际token和符号片段属于不同内容来源，不能用符号名字声称等同某段实际token。实际token的128-token分段哈希链只用于可复用身份索引，不改变完整输入序列，不以请求长度或session推断共享。
