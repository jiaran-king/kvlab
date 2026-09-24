# F12-A / F12-B 同容量复用复核

本报告比较同一份冻结输入、相同 12 GiB P 侧预算下的两次运行。F12-B 只用于检验运行间差异；它不替代历史 L2/L3，也不与 F12/F24 容量对照拼成同一曲线。

## 验收

- 配对请求：425；A/B 请求键集合一致：`True`。
- A 接受：`True`；B 接受：`True`。
- A/B 资源清理：`True` / `True`。

## 结果

详细逐请求差异见 `paired-requests.csv`，汇总见 `summary.csv`。正的 `delta_adopted_B_minus_A` 表示 B 最终采用更多本地缓存；发送后 TTFT 与入队至首 token 分开保存。

- B−A adopted cache token：`-256`；local compute token：`256`。
- B−A query token：`-32479`；query hit token：`-512`；query calls：`-1`。
- B−A TTFT P95：`0.0599586` s；E2E P95：`1.34948` s。

## 解释边界

两次运行均为闭环回放；即使业务输入冻结，依赖完成、客户端槽位与服务端调度仍可产生不同交错。若两次采用量接近，则本实验未发现明显的同容量运行间分歧；这不能证明历史 L2 的异常已被解释。若采用量明显不同，应把差异定位到逐请求输入、查找/采用记录和阶段时间，不能直接称为缓存实现缺陷。
