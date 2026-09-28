# 后端共用 SSE 发送层设计补充

日期：2026-09-28。用户要求：“还有后端的发送的 SSE 如果没有共用部分，那么也进行修改”。延续本轮设计工作，补充 [design 第 4.4 节](../../design.md#44-后端共用-sse-发送层)，不实施运行代码、不运行应用测试。此前前端复用任务保留。

## 核对与决策依据

| 现状/决定 | 依据及理由 |
| --- | --- |
| 两条路由没有共用发送层 | [channel_routers.py](../../../../../src/logagent/interaction/channel_routers.py) 自行拼接 id/data 和心跳；[routers.py](../../../../../src/logagent/interaction/routers.py) 自行拼接 event/data 和心跳；两处分别创建相同媒体类型/响应头的 StreamingResponse |
| 共用编码、响应和生命周期清理 | 这些是相同的 HTTP/SSE 传输职责，集中在 interaction/sse.py，以函数处理即可，无需建立新 Service 或事件总线 |
| 保留 Agent 数据源适配器 | Agent 需要 after/Last-Event-ID、持久日志补发、等待新事实与终态尾部排空，不能用 Workflow 最新快照替代 |
| 保留 Workflow 数据源适配器 | 新设计需要先订阅后读首帧、版本过滤、慢观察者边界与完整 snapshot，不复制 Agent EventLog |
| 不统一等待模型 | Agent 当前 wait_events(wait_seconds=0.5) 检查状态和事件，Workflow 当前空闲心跳为 15 秒；沿用原数值，源适配器产生心跳信号，共用层发送，避免另建通用等待调度器 |
| 取消和资源释放共用、业务终态各自负责 | HTTP 断开不等于执行停止；共用层关闭迭代器，源适配器释放订阅，异常可见，不伪报成功或自动重新执行 |
| 编码支持可选 event/id | Agent 默认 message + 数字事件 id，Workflow 命名 snapshot；校验服务端帧元数据并 JSON 编码 data，不能把任意字符串拼成多条 SSE 帧 |
| 统计真实删除的重复实现 | 同时列出共用文件及两条路由改动，不把迁出 Workflow 目录的发送职责当作净减少 |

此次补充为内部复用决策，不改变 proposal 或新增对外能力规范；现有 stream spec 的只读订阅、错误可见、快照与断线恢复要求继续适用。

## 后续实施

- [ ] 1. 共用帧编码/心跳/StreamingResponse 和迭代器关闭，删除两条路由内被替代实现；仅保留薄业务数据源适配器。
- [ ] 2. 保持 Agent URL、字段与游标补发；Workflow 使用新 snapshot 协议，保留持久化后发布的边界。
- [ ] 3. 验证默认 message 与命名 snapshot、可选 id、Unicode/正文换行、非法 event/id、心跳和响应头。
- [ ] 4. 验证正常结束、断连、任务取消和数据源异常时释放资源；Agent 终态排空与 Workflow 慢订阅者处理不遗漏，订阅不增加业务调用。
- [ ] 5. 复核路由/共用层职责及生产代码净变化；后续后端测试命令硬超时 60 秒。

## 本轮验证

- [x] 静态核对后端现状，完成设计和新增任务；未改变运行代码。
- [x] `openspec validate redesign-workflow --strict --no-interactive` 通过（退出码 0）；本轮 3 份文档相对链接、围栏、空白及限定目录 `git diff --check` 通过。已审查新增段落与任务，未修改其他设计决定或生产代码。
- [x] 按本轮约束不运行应用测试。
