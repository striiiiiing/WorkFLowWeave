# Mock 文件渠道设计

[Channel 网关](../design.md) · [ChannelConfig 契约](../../../contracts/data-models.md#24-channel-配置)

注册名为 mock，能力为 notification。此渠道实现提案要求的“把通知追加到文件尾部”，用于本地查看和离线验收。

options 只需必填 path，相对路径按 data_dir 解析并在快照固定。采用 UTF-8 可读文本，保留标题和正文换行，不使用 JSON；文件只追加，不覆盖已有内容。

Mock 使用一个专用 logging Handler，不新增渠道类型。Handler 随渠道实例常驻，负责格式化、追加与 flush；同一目标文件复用 Handler 及其写入锁。直接调用专用 Handler，不经过全局日志等级、过滤器或 root logger，通知正文不混入应用诊断日志。

每次 send 创建独立写入结果，初始为未成功。Handler 只有在完整写入并 flush 成功后才标记成功；写入异常记录到本次结果。send 调用后检查该结果，失败或未完成都不能返回 success。状态按本次记录保存，不共享一个可能被并发覆盖的 last_error；不靠文件存在或长度增加推断成功，也不全文件回读。

文件操作放入线程以免阻塞事件循环；写入锁保持到实际 I/O 结束。已经开始写入后的超时、取消或部分写入标记 delivery_uncertain，不自动追加第二次。stop 等待有界清理并关闭 Handler；成功含义是写入并 flush，不承诺断电持久性。

验证多行正文可读、已有文件保留、并发追加不交错，以及写入/flush 失败时调用后检查能返回失败；全局日志禁用不应阻止 Mock 通知。
