# Mock 文件渠道任务

状态：本轮复核缺口已在工作树修复并通过验证，待提交。依据 [Mock 设计](./design.md)、[网关设计](../design.md)及用户最后确认“只给 Mock 增加专用 logging Handler”。旧任务基线 `4dfa8d0` 的 JSON Lines 与短生命周期约定已废止。依赖：Channel 网关。

- [x] options 仅 path；按配置快照的有效路径追加 UTF-8 可读标题和多行正文。保留原文件，注册类型仍为 mock，不增加 logging 类型。
- [x] 专用常驻 logging Handler 完成格式化/write/flush；同路径共享 Handler 与锁，引用释放后关闭。直接调用专用 Handler，不受 root logger、日志等级、过滤或全局 logging.disable 影响。
- [x] 每次调用有独立完成结果，初始未成功；只有完整写入及 flush 成功后标记成功，捕获的 I/O 错误保留到该记录。send 调用后检查，不共享 last_error、不按文件长度推测、不全文件回读。
- [x] 文件操作在线程执行；实际写完才释放锁，取消/部分写入/超时保留不确定性，无自动补写；关闭等待有界清理。代码保持最小，不引入队列或日志框架。
- [x] 测试可读多行、重复发送、同路径并发、write/flush 错误、全局日志禁用、取消及关闭（60 秒）；lint、构建、真实文件追加烟测。

## 初版实现与验证（2026-09-17，后续复核发现缺口）

- MockFileChannel 使用专用 logging.Handler 直接写入 UTF-8 可读标题/正文，保留原文件并 flush；同路径 Handler 通过进程内注册表共享线程锁，引用释放后关闭。调用不经过 root logger、等级或全局禁用状态。
- 写入在线程执行，Handler 的每次 emit 独立完成；异常直接传播给 ChannelManager，由回执记录失败/不确定投递。
- 已同步 Workflow integration 对新设计文本输出的断言；定向回归通过，Ruff 通过。

### 决策依据与默认值

- 直接调用专用 `_FileHandler.write` 而不走 `logging.Handler.handle/emit`：依据 Mock design“直接调用专用 Handler，不经过全局日志等级、过滤器或 root logger”。`handle` 会先执行 handler 过滤器，过滤器返回 False 时 `emit` 不执行而 `send` 仍返回成功，这是本轮修复的真实缺陷。
- `_WriteResult.started` 在真正调用 `stream.write` 之前置位：依据 Mock design“已经开始写入后的超时、取消或部分写入标记 delivery_uncertain”。`write` 抛错无法证明一个字节都没落盘，因此短写和 write/flush 异常都按 uncertain 上报；未 start 就失败的调用保持 `uncertain=False`。
- 短写按 `EIO` 处理并把 `written`/`expected` 写入 details：文本流 `write` 返回已写字符数，少于预期即不满足 design“完整写入并 flush 成功后才标记成功”；不补写、不重试，遵循“无自动补写”。
- 关闭等待使用 `_STOP_TIMEOUT = 5.0`：与 ChannelManager 的默认关闭预算一致；装配层可通过 `ChannelManager.stop_timeout` 再包一层有界等待，Handler 自身不接收注入预算，保持最小实现。

### 本轮复核缺口的修复（2026-09-17）

- 每次 `send` 构造独立 `_WriteResult`（初始 `success=False`），Handler 完整 `write + flush` 后才置成功；`send` 返回前检查结果，失败抛 `ChannelDeliveryError(code="mock_write_failed")`，details 保留 operation、exception_type、errno、written、expected，不按文件长度或全文件回读推断成功。
- 写入路径绕开 root logger、Handler 等级、Handler 过滤器和 `logging.disable`；`_HANDLERS` 同路径共享 Handler 与线程 I/O 锁，`start` 复用已打开的流，`stop` 以实例级 `_released` 保证单实例幂等、引用归零才关闭流。
- 取消时保留已知投递事实：已经开始写入的取消在线程内完成该次写入，同时向上抛 `CancelledError`，不追加第二次。
- 证据：新增 `tests/test_channel_mock.py` 11 项测试（多行可读与保留原文件、24 路并发不交错、过滤器/等级/全局禁用不影响、write/flush OSError、短写 uncertain、失败不污染下一次、取消只写一次、共享引用与 stop 幂等）；全量 `468 passed`，Ruff 通过；Workflow 集成断言改为完整文本比较。

### 未覆盖的边界

- `_HANDLERS` 是进程内全局注册表，用于满足“同一目标文件复用 Handler”；同路径实例必须通过 `stop` 释放引用，测试之间共享进程时需要显式清理。
- 线程内的文件写入无法被取消打断：取消发生在写入开始后时，该次写入仍会完成，mock 只上报不确定性并停止追加第二次，不尝试回滚已写内容。
