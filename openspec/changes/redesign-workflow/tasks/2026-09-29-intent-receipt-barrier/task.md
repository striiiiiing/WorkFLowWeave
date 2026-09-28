# Intent checkpoint 提交屏障修复

日期：2026-09-29。工作区：`.worktree/redesign-workflow`，分支：`feat/redesign-workflow`。依据：[design](../../design.md) 第 3、5、6 节、[流式执行规范](../../specs/workflow-stream-execution/spec.md)、[通知规范](../../specs/workflow-parallel-notification/spec.md) 以及第 13 节的单次 `astream_events` 与唯一事实消费者约束。

## 发现的业务边界错误

`intent` 节点返回后，LangGraph 可以继续执行同一 notify 分支的 `receipt`；但 `astream_events` 的唯一订阅消费者是异步观察者，可能还没有把该 checkpoint 投影成长期 `SessionStore` 事实。测试渠道在真正发送前读取 `intent:first:one` 得到 `None`，两个发送分支都没有进入“已确认意图”状态，5 秒后测试超时。

这不是 checkpoint 没有提交，而是执行推进与事实投影存在竞态。若直接发送，外部渠道可能已经产生副作用，而长期存档、恢复查询和发送前的业务检查仍看不到对应 intent，形成“外部已发送、内部不可见”的业务边界错误。

## 修复不变量与实现

- `intent` 注册 `(execution_epoch, output_id:channel_id)` 后创建进程内 Future 屏障；同一身份重复观察不重复创建 Future。
- `intent` 与 `receipt` 之间增加异步屏障节点。只有 `CheckpointSubscription` 完成唯一 intent checkpoint 的事实追加后，才释放该 Future 并允许 receipt 调用渠道。
- 事件流或事实归档失败时，`run_graph` 释放所有等待者并传播原始异常；receipt 不发送，不以静默成功或补发掩盖归档失败。
- intent 节点改为异步节点，因为 LangGraph 可能把同步节点放在线程执行器，线程中没有 asyncio event loop；Future 只在运行事件循环的节点内注册。

该屏障只协调本次进程内执行顺序，不替代 LangGraph checkpoint，也不新增外部 broker 或第二套持久事件日志。长期事实仍由唯一事件消费者追加，发送状态仍由 checkpoint 的 intent/receipt 语义决定。

## 验证记录

- 已观察到原始测试中的 5 秒超时，并确认根因是发送前 SessionStore 缺少 intent，而非渠道凭据或消息格式错误。
- 修复后并行通知回归与流进度组合测试已有通过记录；最终验收仍需在本 worktree 逐命令硬超时 60 秒复跑，并补充归档失败、取消和重复注册边界。
- 不能以本记录替代第 13 节其余 storage、前端、浏览器和完整恢复验收；未完成项保持未勾选。

## 记录边界

本次只追加实施/验收记录，不修改 `proposal.md` 或 `design.md`。屏障是对现有设计中“意图提交后才允许确定回执”和“唯一事实消费者”的实现补足；若未来设计改变发送准入语义，应新增任务并重新确认，而不是覆盖本记录。
