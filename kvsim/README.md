# KVLab

当前原生工具的多 P 冻结路由、三个调度参数与带来源容量对照入口见 [KVLab v2 START_HERE](../output/kvsim/native-v2/START_HERE.md)。此前替换负载和可选容量的完整案例仍见 [KVLab v1 START_HERE](../output/kvsim/native-v1/START_HERE.md) 与 [v1 验收状态](../output/kvsim/native-v1/ACCEPTANCE_STATUS.md)。下面的 425 请求三档材料是首个已完成的受控案例。

## 原生 vLLM 离线结果（H20）

页面主入口现可导入 [425 请求三档结果包](../output/kvsim/native-stage-a/replay425-delivery/native-results.json)，切换 12／24／48 GiB，查看逐请求采用量、输入处理量、逻辑步状态及选定窗口的原生缓存事件。完整对照、历史参考、指标口径和限制见 [实验报告](../output/kvsim/native-stage-a/replay425-delivery/REPORT.md)、[正式输入核查](../output/kvsim/native-stage-a/historical-capture-f12/CAPTURE_AUDIT.md)与 [资产核查](native/ASSET_AUDIT.md)。结果包由 Python 原生 Scheduler 驱动产生；页面只读展示，不参与该实验的调度或缓存决策。旧版 Ascend 浏览器机制模拟保留在折叠区。

当前主结果使用 [C12 捕获并供 F12/F24 冻结复用的 P 侧 token workload](../output/kvsim/native-stage-a/historical-capture-f12/replay425-f12-captured-workload.json.gz)，不是仅凭长度构造的输入。此前的 [trace 驱动合成 workload](../output/kvsim/v03/replay425-request-admission-workload.json)及其扫描仍作为对照保留。两份输入仅有 30/425 条 token 数组完全相同，但在本离线协议下逐请求缓存决策一致。三档均完成 425/425；12 GiB 的模拟查询命中率 90.53%，与历史 L2 的 42.16% 相距很大，因此该实验是受控容量扫描，不能称为 H20 历史精确复现。逻辑步不代表实际延迟。

在 H20 已安装的 vLLM 0.26.0 CPU 环境中，可通过 `kvsim/native/jobs/run_native.slurm` 和 [条件文件](native/h20-conditions-events.json)复跑；必须按项目服务器指南通过 SLURM 提交，不能在登录节点直接运行计算。每档输出 manifest、summary、requests、events 和 steps。把结果复制回含历史参考材料的本地工作区后，运行 `python -m kvsim.native.compare <输出目录>`、`python -m kvsim.native.prefix_evidence <输出目录> <workload.json>`、`python -m kvsim.native.bundle <输出目录> <输出目录>/native-results.json` 生成对照和页面结果包。

## 旧版浏览器机制模拟（Ascend）

离线 KV Cache 模拟器。直接打开 [KVLab.html](KVLab.html)，或在 macOS 双击 `启动.command`。网页不需要 Python、Node、本地服务或网络；不运行模型推理。关闭页面即停止，刷新会清空本页方案，请先导出。

## 请求来源

- **简单合成负载（机制测试）**：验证规则的小型案例。
- **导入 Replay workload**：输入内容、依赖和等待已冻结，可调整 P 实例、路由、执行规则与容量。
- **导入完整 scenario**：保留文件中的请求与执行设置，只覆盖页面容量。

原始 Replay plan 不是 workload。未知或失败的导入会报错并使旧输入失效，不会回退到示例。425 案例只作为文件保留，不设主界面专属选项。

可直接导入的文件：

- [15 请求／3 会话小案例](../output/kvsim/v03/replay-small-workload.json)
- [425 请求／6 会话、历史请求准入补丁语义](../output/kvsim/v03/replay425-request-admission-workload.json)

两者都是原 PromptBuilder 与固定 tokenizer 生成的 **trace 驱动合成内容**，使用确定性输出替身，不是原始历史对话逐 token 回放。425 文件约55MB，不嵌入HTML。

## 使用

导入 workload → 确认请求数、来源和执行模式 → 调整条件 → 运行或扫描容量 → 点击请求解释 → 导出场景、结果、CSV或曲线。方案可单独删除或全部清空。结果绑定运行时快照，编辑参数会标记待重跑。

容量是每 rank 已分配的 KV 预算，不是设备总显存。P 实例之间不共享缓存；一个 TP4 实例包含多个 rank。缓存复用粒度与物理布局由预设联动，不能作为独立任意参数。部署最大输入长度可选，不含本轮输出；留空不代表真实模型无限上下文。

固定事件模式用于机制核验。负载驱动模式从采用的前缀继续计算，根据依赖、等待及资源约束推进；所有虚拟时间参数都是明确的近似，不预测真实 TTFT、E2E或FLOPs。详细规则见 [WORKLOAD.md](WORKLOAD.md)。

工具上限：2,000 节点、累计输入1亿 token、10万事件、单次网页运行/扫描90秒、模拟核心85秒计算限制、50万个实际创建的物理块对象。大实际token文件仍会消耗浏览器内存，建议先用小案例。资源超限不同于格式错误、部署不支持或固定规则下容量不可执行。

## CLI 与离线导出

网页和 Node CLI 共用 `browser/core.js`：

```bash
node kvsim/browser/cli.cjs output/kvsim/v03/replay-small-workload.json output/kvsim/my-sweep 8 12 16 24
node kvsim/browser/cli.cjs output/kvsim/my-sweep/1-8GiB/scenario.json output/kvsim/my-rerun
```

CLI每点输出 scenario.json、result.json、summary.json、resolved_config.json、requests.csv。完整结果包含实际事件和只读解释。

原 Replay 负载生成由独立 Python exporter 完成，使用原 AgentInfer 源码。完整命令、capture格式、默认chat模式范围及并发配置见 [WORKLOAD.md](WORKLOAD.md)。使用其他 trace/config 无需改 KVLab 核心。Python缓存实现仅保留为旧固定事件规则的对照基准，不是新 workload 执行入口。

## 开发与验证

```bash
python3 kvsim/build_html.py
kvsim/.venv/bin/python -m unittest discover -s kvsim/tests -v
node kvsim/tests/browser_core.cjs
node kvsim/tests/workload_core.cjs
node kvsim/tests/token_prefix.cjs
node kvsim/tests/ui_flow.cjs
node kvsim/tests/native_results.cjs
kvsim/.venv/bin/python -m kvsim.tests.check_tokenizer_capture
kvsim/.venv/bin/python -m kvsim.tests.audit_replay_content
```

旧版结果与限制见 [ASSETS-v03.md](ASSETS-v03.md)、[RULES.md](RULES.md)、[AUDIT-v03.md](AUDIT-v03.md)。源码分文件维护，build_html.py生成单文件交付。UI控制器测试使用DOM/Worker替身，不等同真实浏览器验收；浏览器工具的 `file://` 策略禁止代开本地页面。

此前竞争案例中的12～16GiB收益台阶已确认受错误回收策略影响，相关结论失效。修正后8～24GiB都达到该案例31.9534%的复用上限；旧记录保留作更正证据。不得将旧曲线或两份自写实现一致，当作实机容量预测的独立证明。

### 独立导入实验条件

“设置一个场景”顶部可导入/导出 `kvlab-conditions/v1` JSON。文件包含 config、p_domains、routing_mode（spread/p0/manual）、routing（session→P）、execution_mode、execution 及 capacities；不包含 trace。先导入条件、再导入 Replay workload 时，已导入的执行参数不会被 workload 默认值覆盖。导入失败保留原条件。完整场景导入会回填全部可见参数；仍保持冻结路由/事件，只允许改容量。逐请求异构路由显示只读请求 ID→P 映射，请用完整场景导出保留它。

可直接使用 `output/kvsim/replay425-study/conditions.json`（项目根目录下），配合先前的 Replay 425 workload。条件变化后已有结果仍绑定原场景，需重新运行。
