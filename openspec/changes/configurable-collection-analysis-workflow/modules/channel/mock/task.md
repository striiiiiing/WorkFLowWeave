# Mock 文件渠道任务

状态：本轮复核缺口已在工作树修复并通过验证，待提交。依据 [Mock 设计](./design.md)、[网关设计](../design.md)及用户最后确认“只给 Mock 增加专用 logging Handler”。旧任务基线 `4dfa8d0` 的 JSON Lines 与短生命周期约定已废止。依赖：Channel 网关。

- [x] options 仅 path；按配置快照的有效路径追加 UTF-8 可读标题和多行正文。保留原文件，注册类型仍为 mock，不增加 logging 类型。
- [x] 专用常驻 logging Handler 完成格式化/write/flush；同路径共享 Handler 与锁，引用释放后关闭。直接调用专用 Handler，不受 root logger、日志等级、过滤或全局 logging.disable 影响。
- [x] 每次调用有独立完成结果，初始未成功；只有完整写入及 flush 成功后标记成功，捕获的 I/O 错误保留到该记录。send 调用后检查，不共享 last_error、不按文件长度推测、不全文件回读。
- [x] 文件操作在线程执行；实际写完才释放锁，取消/部分写入/超时保留不确定性，无自动补写；关闭等待有界清理。代码保持最小，不引入队列或日志框架。
- [x] 测试可读多行、重复发送、同路径并发、write/flush 错误、全局日志禁用、取消及关闭（60 秒）；lint、构建、真实文件追加烟测。

## 本次修正与主代理审查（2026-09-17）

- 主代理对照 Mock design 复核 `dbf2494` 后全部 Handler 改动及测试；proposal/design 未修改。专用 logging.Handler 只负责通知文本，直接调用 write，不经过 root logger、等级或过滤器。
- 每个 send 使用独立 _WriteResult；仅 write 返回完整字符数且 flush 成功才标记成功。None 返回值、短写、write/flush 异常均失败，不补写、不以文件长度推断成功。details 只含阶段、异常类型、errno 和计数。
- 同路径 Handler 共享 I/O 锁和引用计数，start 幂等；最后一个引用关闭期间仍保留池条目，新所有者沿用同一把锁，避免重复 Handler 与关闭/open 竞争。
- 主代理发现并修复：取消后的 start/write 线程未被跟踪、stop 可能先关闭后被延迟 start 重新打开，以及 write 未返回完整计数仍报成功。每实例保留未结束 I/O task，stop 先排空再释放引用；取消不能停止实际线程操作，已开始写入的投递仍不确定且不重试。
- stop 的独立清理任务归实例所有，调用者等待上限 5 秒；超时显式报错且保留任务，后续 stop 可继续等待同一清理结果。默认值与网关本地关闭预算一致，不覆盖文件写入结果的事实。无法强杀阻塞的文件系统线程；此限制不被伪装成成功关闭。

## 验证

- Mock 专项 15 passed，0.65 秒，exit 0；含取消 start、取消 write、超时后再次 stop、新所有者与关闭竞争、未知写入长度等回归。
- 与 Channel/Workflow 集成共 49 passed，3.38 秒，exit 0；相关 Ruff 通过。构建、真实文件追加 smoke 与全套最终结果收取后补录。

提交前验证：全套 490 passed，34.13 秒，exit 0；uv build 成功；真实文件两次发送仅一次创建、完整文本相等及重复 stop smoke 成功。所有审查由主代理完成。
