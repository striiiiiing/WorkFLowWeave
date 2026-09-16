# Mock 文件渠道任务

状态：待执行。依据 [Mock 设计](./design.md)、[网关设计](../design.md)及用户最后确认“只给 Mock 增加专用 logging Handler”。旧任务基线 `4dfa8d0` 的 JSON Lines 与短生命周期约定已废止。依赖：Channel 网关。

- [ ] options 仅 path；按配置快照的有效路径追加 UTF-8 可读标题和多行正文。保留原文件，注册类型仍为 mock，不增加 logging 类型。
- [ ] 专用常驻 logging Handler 完成格式化/write/flush；同路径共享 Handler 与锁，引用释放后关闭。直接调用专用 Handler，不受 root logger、日志等级、过滤或全局 logging.disable 影响。
- [ ] 每次调用有独立完成结果，初始未成功；只有完整写入及 flush 成功后标记成功，捕获的 I/O 错误保留到该记录。send 调用后检查，不共享 last_error、不按文件长度推测、不全文件回读。
- [ ] 文件操作在线程执行；实际写完才释放锁，取消/部分写入/超时保留不确定性，无自动补写；关闭等待有界清理。代码保持最小，不引入队列或日志框架。
- [ ] 测试可读多行、重复发送、同路径并发、write/flush 错误、全局日志禁用、取消及关闭（60 秒）；lint、构建、真实文件追加烟测。

## 初版实现与验证（2026-09-17，后续复核发现缺口）

- MockFileChannel 使用专用 logging.Handler 直接写入 UTF-8 可读标题/正文，保留原文件并 flush；同路径 Handler 通过进程内注册表共享线程锁，引用释放后关闭。调用不经过 root logger、等级或全局禁用状态。
- 写入在线程执行，Handler 的每次 emit 独立完成；异常直接传播给 ChannelManager，由回执记录失败/不确定投递。
- 已同步 Workflow integration 对新设计文本输出的断言；定向回归通过，Ruff 通过。

### 本轮复核

- `dbf2494` 只是初版提交，不能认定专项验收完成。设计要求每次记录独立的完成结果，只有完整 write/flush 后设置成功，再由 send 调用后检查；当前只 await Handler.handle，可能被过滤器跳过而仍返回成功。
- 共享 Handler 每次 start 都重新打开流，重复 stop 会再次减少共享引用；需要一次初始化、每实例一次释放，并在实际 I/O 结束前保持写入/关闭协调。线程取消不会自动终止文件操作，需要显式记录尚未完成的操作并有界收束。
- 补充同路径并发、短写/flush 失败、禁用日志及过滤器、取消/关闭专项测试；文本集成断言应比较完整输出，不能仅检查子串而遗漏重复发送。
