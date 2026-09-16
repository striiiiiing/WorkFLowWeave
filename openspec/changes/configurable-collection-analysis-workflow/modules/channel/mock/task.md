# Mock 文件渠道任务

状态：待执行。依据 [Mock 设计](./design.md)、[网关设计](../design.md)及用户最后确认“只给 Mock 增加专用 logging Handler”。旧任务基线 `4dfa8d0` 的 JSON Lines 与短生命周期约定已废止。依赖：Channel 网关。

- [ ] options 仅 path；按配置快照的有效路径追加 UTF-8 可读标题和多行正文。保留原文件，注册类型仍为 mock，不增加 logging 类型。
- [ ] 专用常驻 logging Handler 完成格式化/write/flush；同路径共享 Handler 与锁，引用释放后关闭。直接调用专用 Handler，不受 root logger、日志等级、过滤或全局 logging.disable 影响。
- [ ] 每次调用有独立完成结果，初始未成功；只有完整写入及 flush 成功后标记成功，捕获的 I/O 错误保留到该记录。send 调用后检查，不共享 last_error、不按文件长度推测、不全文件回读。
- [ ] 文件操作在线程执行；实际写完才释放锁，取消/部分写入/超时保留不确定性，无自动补写；关闭等待有界清理。代码保持最小，不引入队列或日志框架。
- [ ] 测试可读多行、重复发送、同路径并发、write/flush 错误、全局日志禁用、取消及关闭（60 秒）；lint、构建、真实文件追加烟测。
