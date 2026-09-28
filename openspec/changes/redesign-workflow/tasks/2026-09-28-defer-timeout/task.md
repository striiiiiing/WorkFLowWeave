# 原生 defer、Send 超时与 RetryPolicy

## 依据与边界

用户要求子图 checkpoint 清理改为 defer，全部业务结束后统一清理；超时和重试交由 LangGraph，耗尽后错误向外抛。依据更新后的 design §1/§5.2；本记录新增，不覆盖之前采用外部维护 worker 清理的历史任务。

当前 LangGraph 1.2.12 的 Send 只有 timeout 参数，没有 retry_policy 参数；后者在 add_node 配置。TimeoutPolicy 是 asyncio 协作取消，FastAPI 不提供异步函数抢占机制，阻塞代码仍须在能力实现中使用线程/进程或异步 I/O。本轮不引入通用隔离执行器。

## 实施与验证

- [ ] finish 后添加 defer cleanup，补齐归档后统一删除非空子图 namespace，保留父图入口。
- [ ] 删除逐阶段 completed/namespace_archived 自建清理判定，外部流不负责触发子图删除。
- [ ] 事件消费使用 sync loop 事件自身投影，覆盖清理已发生但事件尚在排队的情况。
- [ ] collect/analyze/aggregate 使用 Send timeout 和目标节点 RetryPolicy；单次能力不内部叠加整体预算与重试，异常耗尽向外传播。
- [ ] 确认通知的不确定投递与重试语义后实施，避免未确认的重复发送。
- [x] Luna max 真实验证 defer 在全部普通分支结束后执行；节点异常或 interrupt_before 时不执行；Send 与 add_node 的参数签名符合上述边界。
- [ ] 完整链路、取消恢复、阶段重跑、归档交接、并发隔离与异常传播回归；静态检查/构建。

## 默认值

采用用户给出的 RetryPolicy 默认值：最多 3 次（含首次）、首次等待 0.5 秒、倍率 2、上限 128 秒、抖动开启。run_timeout 来自来源/模型/渠道原配置，不新设秒数；idle_timeout 未指定，不擅自设定。正常返回 failed 的业务结果不自动当成异常重试。
