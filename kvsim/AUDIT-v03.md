# v0.3 完成审计（2026-09-22，尚未宣布 Goal 完成）

审计依据：GOAL-v03.md 全文。浏览器真实交互尚待确认，不把 DOM 单元测试视为浏览器验收。

|目标条款|当前证据|状态及限制|
|---|---|---|
|1 架构职责|replay_export.py 调用原 analyzer/planner/sampler/PromptBuilder；core.js 消费冻结内容；HTML/CLI 共用核心|已实现；无JS PromptBuilder|
|2 资产|ASSETS-v03.md；replay-source-comparison.json；tokenizer/source.json；server-capture-parity.json|源码/版本、补丁、tokenizer与部分历史capture核对完成；未证明历史Ascend容器全部本地补丁一致|
|3 回收机制|test_source_pool.py；test_source_lifecycle.py；reclaim-correction.json|直接源码队列/引用/重复hash索引对照；无hash批量前插、带hash尾插、惰性未使用区间|
|4 独立验证|test_source_lifecycle.py、test_core.py源码mask/table测试|窗口释放、保留mask、准入vs分配、共同边界均覆盖。协调器测试用组探针替身隔离固定点算法；非完整vLLM端到端等价声明|
|5 schema|validateWorkload/inspectImport；WORKLOAD.md；workload_core.cjs|runtime身份、实际token、来源、等待、metadata校验；不接受未知格式回退|
|6 exporter|check_tokenizer_capture.py；audit_replay_content.py；28项Python测试中的Replay测试；55MB完整workload|7份已保存服务端tokenization逐token匹配；固定5分支及13祖先与原Builder比较；确定性输出替身明确标注。只支持所述纯文本DSV4默认chat模式|
|7 workload/scenario|ui_flow.cjs；workload_core.cjs|控制器单元验证格式分流、失败使旧输入失效、冻结场景只改容量；真实文件选择器交互待确认|
|8 双执行模式|driveWorkload复用simulate事件处理；workload_core.cjs|固定事件保留；动态命中后只计算5920而非两个零步骤；实际事件导出|
|9 执行语义|WORKLOAD.md；workload_core.cjs；历史request_admission.py已核对并记录|显式区分会话并发、在途请求、P槽；等待取整、传输最早下一tick、D近似、同刻顺序已记录；不复刻HTTP/构造时延竞争|
|10 冻结容量扫描|acceptance_v03.cjs及acceptance.json|四个容量请求/token/依赖/路由/外部等待一致；16GiB完整场景重跑逐字段一致|
|11 诊断|Pool.snapshot；diagnostics.prefix_opportunities；explanation；各P表|首次使用/无hash复用/替换分开；共同内容、长度边界、采用量分开。联合checkpoint历史未单独追踪，明确标注，不能从未命中推断淘汰|
|12 案例验收|tests目录及output/kvsim/v03各测试记录；小trace/config/workload及两组扫描|普通续接、容量淘汰、D输出、引用、主子依赖、取消等覆盖；不同trace/seed/重复采样已导出运行。实际浏览器导出/导入重跑待用户确认|
|13 UI与旧结论|template.html、KVLab.html、旧报告更正顶部注释|无425专属选项；直观名称、删除清空、只读解释；DOM控制器测试通过；URL安全策略阻止自动化file://真实验收|
|14 顺序|ASSETS-v03.md阶段记录、reclaim-correction.json|先修回收并独立验证，旧案例更正后再接Replay；其他源码对照后补齐，最终统一回归|
|15 交付|KVLab.html、browser/cli.cjs、replay_export.py、WORKLOAD/README/RULES、源文件、案例与测试证据|代码和离线流程已交付；浏览器真实使用流程未验收，Goal因真实浏览器验收受阻（blocked）|

## 已有证据的准确含义

- Python与JS一致只证明移植一致，独立源码对照单列。
- 7份历史tokenization与新离线渲染一致，不意味着425请求使用了历史模型输出。425是trace驱动合成内容。
- 旧错误回收策略的容量台阶已撤回。修正后原小案例8～24GiB均31.9534%，替换0。
- 源码默认会话并发3与历史request-admission补丁不同。两组负载/扫描分别保存，不互相冒充。
- 历史补丁语义的当前虚拟执行：8GiB仅完成82/425后准入失败；12/16/24GiB完整完成，采用68.2468%。8GiB的部分采用比例不作为完整容量点。
- 固定事件受控案例：1475物理块和1500物理块均完整执行，前者发生必要状态替换、续接采用0；后者采用16384且替换0。这是机制测试，不是生产收益结论。

## 剩余事项

真实浏览器中打开单文件，导入小workload、扫描、查看解释、删除方案、导出scenario再导入重跑。已经通过异步问题请用户确认；浏览器工具此前的file://安全拒绝没有被绕过。需要用户结果或允许的浏览器验证能力，才能将这项标为已验证。

## 最后状态核对

Goal 已标为 blocked，不是 complete。相同 file:// 浏览器策略限制已持续多轮；当前没有待运行进程或可替代真实界面验收的自动化动作。代码、核心测试及离线文件重跑证据保持不变。待用户确认导入、扫描、解释、删除、导出及重新导入流程，或获得不绕过安全策略的验证能力后继续。
