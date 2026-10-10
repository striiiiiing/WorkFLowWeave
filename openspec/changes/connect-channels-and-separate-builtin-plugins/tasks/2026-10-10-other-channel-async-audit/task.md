# 其他通知渠道异步 I/O 审计

## 范围与依据

本任务只审计并修正 `src/workflowweave/plugins/channel/README.md` 列出的其他渠道，继承现有 `proposal.md` 与 `design.md` 的渠道生命周期、单次发送超时和取消回收约束；不修改 proposal/design。依据包括已安装的可选 SDK 源码、渠道适配器调用链和受控 loopback/替身测试。

## 结论与决策

- Telegram 的 Bot API 与 polling 调用本身是 async，但 `ApplicationBuilder.build()` 默认同步构造两套 `HTTPXRequest`。构造 `httpx.AsyncClient` 会同步创建 SSL context，并可能读取 CA 文件。把两个 request 对象的构造放入 `asyncio.to_thread`；Application 和 request 的 asyncio 生命周期仍在主 loop 创建和关闭。取消时等待 worker 收尾并关闭已构造 request，避免线程继续留下客户端。
- QQ 的 REST、token、Gateway 和文本消息路径均使用 aiohttp async；适配器没有调用 SDK 明确阻塞的 `Client.run()`。SDK 的冷 `import botpy`（本机约 1.58 秒）也已放入线程，避免首次启用拖住主 loop。SDK `Client.__init__` 默认安装 `TimedRotatingFileHandler`，后续日志 emit/flush/轮转在网关回调线程中同步写盘。适配器清理 SDK 已有 handler，使用 `bot_log=None, ext_handlers=False`，让日志向应用 logger 传播，不为每个 QQ 实例创建 `botpy.log` 文件 sink。
- Email 使用 `aiosmtplib`；已安装版本把 `socket.getfqdn` 与 TLS context 构造放进 `asyncio.to_thread`，SMTP connect/login/send/quit 均 await。`EmailMessage` 构造是有限的本地 CPU 工作，没有证据表明它造成这次卡顿，因此不扩大改动。
- file 渠道的 start、write/flush、close 已经通过 `asyncio.to_thread` 并有取消后 drain；构造阶段只做路径规范化和线程锁引用计数，没有证据表明会产生长时间阻塞，因此不搬移整个构造过程。
- wechat_openclaw 将 SDK、认证、存储和 HTTP 放在独立 Node bridge 进程；Python 侧只 await 子进程 stdin/stdout，路径 resolve 是有限本地操作。保持入站 handler 的 await 顺序，避免为性能引入 ack 乱序。

## 工作与验证

- [x] 追踪 Email、file、QQ、Telegram、wechat_openclaw 的启动、发送、接收、停止调用链。
- [x] Telegram 新增受控阻塞 request 构造回归：worker 阻塞期间事件循环仍可调度；取消清理请求对象。
- [x] QQ 新增 SDK contract 回归：不会安装同步轮转文件 handler；既有 QQ SDK contract 12 项通过。
- [x] Telegram/QQ/适配器回归：`24 passed`（单命令硬超时 60 秒）。
- [x] Ruff 检查改动适配器和测试文件通过。

测试均使用 SDK 替身、真实 SDK 类型和 loopback/受控阻塞，不发送真实平台消息。
