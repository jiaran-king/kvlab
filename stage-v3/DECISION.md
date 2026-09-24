# 离线审查与 M2 决定（运行前）

M1的失败请求：源5c7c6017-db96-4e9c-9b85-516c206fa824，runtime bc545f2b-f725-57d5-b0df-f53d2716ec44，subagent第4轮，计划28577输入/89输出。客户端900.034秒ReadTimeout，13条后继依赖跳过。

新核实的链路事实：
- P日志1269–1270行在01:49:28记录同一D内部ID chatcmpl-0a60d905-3a63-4198-966a-0e2fa6e83c4e-b6439228 的ready等待超时；D日志467–468行收到同一错误。
- 实际安装connector代码1252–1296行说明D元数据抵达P后，P按transfer_id查找或新建SendBlockMeta，等待其ready事件；超时返回FINISH+err_reqs。2001–2021行在request_finished路径带block_ids元数据时设置ready。因此可以确认P侧ready事件未按期置位，而不是仅猜测D丢失一个已发送ready信号。对应KV数据传输未走到ready之后的正常发送路径；是否曾有此前部分活动无逐请求记录。
- Proxy日志存在一个 `send_request_to_service` Task-316的httpx.ReadError，栈位于Proxy→P HTTP响应头读取。Proxy把P请求放入后台task，只在D流结束后await；因此P失败可以未及时传播到D等待链路。没有时间戳和request_id，不能直接证明它就是超时请求，也不能证明P是否收到/完成该具体prefill。
- ReplayTransport不发送X-Request-Id；Proxy生成随机UUID，而Replay计划有独立runtime_request_id。旧日志没有映射，无法补证。累计P计数和成功HTTP响应只作聚合佐证，不能替代逐请求完成证明。

因此三问的结论：P该请求prefill是否完成=未知；D→P的connector请求确实抵达并在P等待ready，ready之后的正常传输未发生；ready为何未置位=未知，Proxy→P HTTP读错误是有源码支持的上游异常候选，不归因于24GiB容量。

定向复现选择：上下文链仅4条(源135–138)，但首条还依赖lead发送时序；抽出单链会丢失原并发、缓存竞争和HTTP连接复用历史。针对当前HTTP传输错误候选，短链通过不能回答关键问题，完整上下文/连接历史重建又需要新适配。按用户已接受的例外路径跳过小复现，不新增适配框架，直接使用唯一一次完整M2作为复现性检验。该决定在M2提交前记录，不是失败后的择优操作。

M2保持24GiB P/48GiB D、四卡同节点、全部174计划、并发3、seed0、原输入输出、900秒timeout、两条预热→P reset→正式metrics协议。只在Proxy加6类少量阶段日志：proxy_received(seed+UUID)、P start/response/error、D headers/first raw chunk/end。没有更改request body、headers、连接池、超时、调度或异常控制流，不修复潜在bug。174个backend_sampling_seed唯一，供原计划映射到Proxy UUID；P/D响应header用于继续关联。该日志差异明确披露，不能宣称完全相同二进制或严密因果实验。

阶段预算独立：最多1次完整M2（旧4次不修改），失败也计入；不自动重跑。若同错误复现，保留新映射和失败证据，在已有日志范围内定位，不新增完整回放。资源与清理复用已验证脚本。启动修复最多30分钟、同一故障有依据修正一次。
