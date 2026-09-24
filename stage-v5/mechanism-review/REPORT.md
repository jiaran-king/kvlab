# 12 GiB 前缀复用损失的定向机制分析

## 1. 范围与结论

本分析使用 C12、F12 和 F24 的已保存 CPU 摘要，针对固定输入配对中出现的缓存采用差额，检查实际输入前缀、混合 KV cache 查找边界以及现有事件窗口。未提交新的 GPU 回放，也未修改服务、缓存策略或诊断 hook。

结论分为三个层次：

1. **已确认的运行机制：** F12 与 F24 的 41 条正差额请求都保留了前驱输入的完整实际 token 前缀。查找记录显示，差异发生在混合 KV cache 的共同命中边界；36 条请求由 group 0 的返回边界差异解释，另外 5 条包含联合 group `[1,2]` 对候选边界的进一步收缩。
2. **已确认的性能关联：** 这些查找差异对应 F24 比 F12 多采用 1,313,280 个本地缓存 token。该净差额中，group 0 类占 1,176,320 token（89.57%），联合 group 类占 136,960 token（10.43%）。
3. **尚未确认的触发因素：** 现有事件摘要没有请求 ID、查找位置、引用计数或释放原因，不能判断所需状态是从未形成、在复用前被移除，还是仍存在但不满足联合恢复条件。当前证据也不能把请求交错中的某个请求确定为触发者。

因此，本轮达到“定位到具体查找环节”的目标，但没有得到缓存状态层面的唯一根因。

## 2. 数据与分类

F12 和 F24 各完成 425 条请求，使用相同的实际输入。逐请求对账为 41 条正差额、384 条零差额、0 条负差额，净增量为：

\[
\sum_i (A_{F24,i}-A_{F12,i})=1{,}313{,}280\text{ token}.
\]

所有 41 条正差额请求都满足：`context_mode=append`、存在前驱、`lcp_tokens == predecessor_input_tokens`。因此，本次配对的正差额不能归因于这些请求的前驱 token 前缀变短。

| 查找差异类别 | 请求数 | F24−F12 采用增量 | 占净增量 |
|---|---:|---:|---:|
| group 0 返回边界不同，后续调用不再收缩 | 36 | 1,176,320 | 89.57% |
| 联合 group `[1,2]` 等后续调用继续收缩 | 5 | 136,960 | 10.43% |
| 合计 | 41 | 1,313,280 | 100.00% |

分类脚本为 `build_review.py`，完整配对表仍保留在 `../final-analysis/cpu-3468/paired-requests.csv`。

## 3. 两个代表性请求

完整字段和前驱记录见 `target-requests.csv`。选择规则固定为：group 0 类选择正差额最大的请求；联合 group 类保留已在报告中使用、且明确出现“非零候选被 `[1,2]` 收缩到零”的请求。

### 3.1 group 0 返回边界：`r00000083-815560ad32e534f4`

该请求输入为 51,987 token，前驱输入为 50,849 token，实际 LCP 为 50,849 token。

| 运行 | group 0 首次查找 | 后续联合查找 | 最终采用 |
|---|---|---|---:|
| F12 | candidate 51,986 → returned 0 | candidate 0 → 0 | 0 |
| F24 | candidate 51,986 → returned 50,688 | candidate 50,688 → 50,688 | 50,688 |

F24 相对 F12 多采用 50,688 token。F12 的记录只能证明该次 lookup 没有返回可用的 group 0 前缀，不能证明相应状态从未形成或此前已被移除。

### 3.2 联合 group 收缩：`r00000183-d01c855532666b44`

该请求输入为 41,869 token，前驱输入为 41,663 token，实际 LCP 为 41,663 token。

| 运行 | group 0 首次查找 | 联合 `[1,2]` 查找 | 后续 group | 最终采用 |
|---|---|---|---|---:|
| F12 | 41,868 → 41,472 | 41,472 → 0 | 0 → 0 | 0 |
| F24 | 41,868 → 41,472 | 41,472 → 41,472 | 保持 41,472 | 41,472 |

group 0 的 41,868→41,472 是 256-token 对齐边界，不能单独命名为容量损失。真正限制 F12 最终采用量的是随后联合 `[1,2]` 的边界收缩。由于 `[1,2]` 是同规格 group 的联合查找，不能把该返回值拆成两个独立 group 的最大命中量。

## 4. 源码语义核对

本次使用的 DeepSeek-V4 配置摘要包含 5 个 cache group，`num_blocks=12,393`，scheduler block size 为 256，hash block size 为 4，retention interval 为 `None`：

| group | manager | block size | sliding window |
|---:|---|---:|---:|
| 0 | `FullAttentionManager` | 256 | — |
| 1 | `SlidingWindowManager` | 64 | 128 |
| 2 | `SlidingWindowManager` | 64 | 128 |
| 3 | `SlidingWindowManager` | 4 | 8 |
| 4 | `SlidingWindowManager` | 8 | 128 |

配置证据来自 `stage-v5/formal-3454/query-diagnostic-1271803.jsonl` 的 `effective_cache_config`；C12/F12/F24 的 source identity 与有效配置验收已在 `stage-v5/REPORT.md` 记录。

实现语义如下：

- `stage-v5/source/v1/core/kv_cache_coordinator.py:682-687` 将混合查找实现为单调收缩的 fixed-point 过程。
- `stage-v5/source/v1/core/kv_cache_coordinator.py:721-780` 按 attention group 依次查找，并把每次返回值作为下一组的候选上限。完整 attention group 排在前面；相同规格的 group 会在 `SpecGroup` 中联合查找。
- `stage-v5/source/v1/core/single_type_kv_cache_manager.py:706-715` 中，完整 attention 查找从前缀开始逐 block 扫描，遇到缺失 block 即停止。
- `stage-v5/source/v1/core/single_type_kv_cache_manager.py:900-943` 中，滑窗 group 需要满足窗口内连续 block 和对齐条件；因此它可以把共同候选进一步限制到较短边界。
- `stage-v5/source/v1/core/kv_cache_manager.py:231-241` 使用 coordinator 返回的共同命中长度作为本地缓存采用量；`stage-v5/source/v1/core/sched/scheduler.py:725-762` 也明确区分联合查找结果和 per-group 查找路径。

这些代码能够解释“为什么一个 group 或联合 group 的返回边界会限制最终采用量”，但不能仅凭查找返回值说明状态为何不可用。

## 5. 事件窗口检查

现有 CPU 分析是在完整事件流上执行的；本地交付仅保留边界摘要，未保留三次运行的完整 `kv-events.jsonl`。各运行边界为：

| 运行 | 正式开始前最后序号 | `AllBlocksCleared` 序号 | 正式结束最后序号 |
|---|---:|---:|---:|
| C12 | 0 | 1 | 591 |
| F12 | 1 | 3 | 537 |
| F24 | 2 | 3 | 418 |

原分析逻辑在遇到唯一的 `AllBlocksCleared` 后开始统计；本次已将 `analyze_runs.py` 的条件显式改为：

```text
formal_start_last_sequence < sequence <= formal_end_last_sequence
```

由于三次运行的清空序号都严格大于正式开始序号，显式下界不会改变既有正式窗口计数。已有汇总中的移除条目仍为 F12 217,750、F24 85,939；事件序号连续且 observer 无错误。

事件摘要不包含请求归属、查找候选、block 引用计数或移除原因。因此，移除量只能说明缓存状态变化规模，不能把某一条 `BlockRemoved` 归属于上述目标请求。

## 6. 请求交错与剩余证据缺口

F24 的 `replay-execution.json` 保留了实际发送偏移；F12 的同等逐请求执行时序文件未进入最终 CPU 交付。当前 CSV 保留 query 时间、客户端槽位等待和发送后 TTFT，但没有两次运行都具备的 P 接收/调度/释放事件链。因此，不能用本地现有材料证明某个干扰请求先于目标查找到达并改变了目标状态。

请求交错仍是合理的候选解释：闭环回放中后续任务由当前运行的完成与槽位状态放行，容量变化也会改变处理时间。但本轮证据只能确认“查找边界不同”，不能把交错提升为触发因素。

## 7. 归因等级与最小后续取证方案

当前归因等级为：**机制已定位到查找边界，触发因素未知。** 没有证据支持直接修改缓存实现，也没有证据支持把某个 group 命名为 bug。

若未来需要继续定位，最小取证内容是：在原有查找和事件调用中，对本轮实际出现的目标请求及其必要前驱记录：

1. 每次 group lookup 的候选、返回、最终共同恢复位置和请求 ID；
2. 目标 hash 的首次形成、再次命中、移除/失效及必要的引用或传输完成边界；
3. P 接收、查找、首次成功调度与客户端槽位时间。

这些记录可以区分“前缀状态从未形成/已被移除”和“状态存在但联合恢复条件不允许采用”。应从原有调用透传并记录，不能为观测额外发起 lookup，也不需要先建立全量 block 生命周期数据库。该方案不在本轮执行。

## 8. 复算

```bash
python3 stage-v5/mechanism-review/build_review.py
```

产物：

- `target-requests.csv`：两个目标请求及其前驱在 F12/F24 的完整局部字段；
- `mechanism-summary.json`：全量差额分类、目标选择、有效配置及事件边界；
- `build_review.py`：只读现有 CPU 摘要的复算脚本。

