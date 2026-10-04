# 持久化与切换参考（2026-10-05）

本轮用户最终选择：改绑低频，同步完成后响应；路由/发送高频，只读加锁内存版本，接受内存短暂错误，不增加后台持久化队列或逐条 SQL 对账。以下源码参考用于解释取舍，不扩大本轮范围。

## Codex

源码版本：`openai/codex@c2f7fe89d87ce853900d0b5cb1f5dc4863e44d73`。

- [rollout/src/recorder.rs:1001](https://github.com/openai/codex/blob/c2f7fe89d87ce853900d0b5cb1f5dc4863e44d73/codex-rs/rollout/src/recorder.rs#L1001)：有界 mpsc（256）和单 writer task，顺序处理 AddItems/Persist/Flush/Shutdown；不是每条各开线程竞速写入。
- [recorder.rs:1035](https://github.com/openai/codex/blob/c2f7fe89d87ce853900d0b5cb1f5dc4863e44d73/codex-rs/rollout/src/recorder.rs#L1035)：`record_canonical_items` 仅等待入队；`persist`/`flush` 通过 oneshot 等待 writer 实际处理结果。底层 writer 是异步，并不代表外层操作一定先响应。
- [thread-store/src/local/live_writer.rs:328](https://github.com/openai/codex/blob/c2f7fe89d87ce853900d0b5cb1f5dc4863e44d73/codex-rs/thread-store/src/local/live_writer.rs#L328)：按 thread 加写锁；当前 `durable_write` 的 AppendItems 在入队之后继续 `await recorder.flush()`，随后才进行可重建 SQLite 投影。
- [core/src/session/mod.rs:2487](https://github.com/openai/codex/blob/c2f7fe89d87ce853900d0b5cb1f5dc4863e44d73/codex-rs/core/src/session/mod.rs#L2487)：普通持久化事件先 await persist_rollout_items，再 deliver_event_raw；该函数持久化失败记录错误后仍可交付事件，不能说每条响应必然以落盘成功为前提。
- [recorder.rs:1771](https://github.com/openai/codex/blob/c2f7fe89d87ce853900d0b5cb1f5dc4863e44d73/codex-rs/rollout/src/recorder.rs#L1771)：保留未写成功的 suffix，后续 barrier 可恢复重试；这属于大量会话历史写入的完整 writer 系统，不值得为低频实例改绑照搬。源码的 file.flush 不等同于每条 fsync/断电保证。

结论：当前本地 Codex 不能概括成“先响应用户，再后台持久化”。独立 writer 与调用者等待确认可以同时存在。

## Claude Code

公开仓库版本：`anthropics/claude-code@2bfb629dfaff0c8318047a4beb93cf1dc5b58b18`，仓库主要为说明、插件、示例与 changelog，未公开完整核心 transcript writer。

- [CHANGELOG.md:5490](https://github.com/anthropics/claude-code/blob/2bfb629dfaff0c8318047a4beb93cf1dc5b58b18/CHANGELOG.md#L5490)，2.1.91 明确修复 “async transcript writes fail silently” 导致 resume 链断裂与历史丢失。
- [CHANGELOG.md:5872](https://github.com/anthropics/claude-code/blob/2bfb629dfaff0c8318047a4beb93cf1dc5b58b18/CHANGELOG.md#L5872) 明确提到 memory-extraction 写入与主 transcript 写入竞态。

能确认它存在异步 transcript 写入及真实顺序/错误风险；无法据公开资料证明它每次先回复后保存，也无法证明具体线程、队列或 barrier 实现。这里不将未知实现当作依据。

## CC-Connect

源码版本：`chenhg5/cc-connect@dfad19415a38b00b2c5c288610784d1a7eef337f`。

- [core/session.go:389](https://github.com/chenhg5/cc-connect/blob/dfad19415a38b00b2c5c288610784d1a7eef337f/core/session.go#L389)：SessionManager 用内存 map 与 sync.RWMutex，启动 load JSON；ActiveSessionID（548）只加读锁查 map，不逐次读盘。
- [core/session.go:487](https://github.com/chenhg5/cc-connect/blob/dfad19415a38b00b2c5c288610784d1a7eef337f/core/session.go#L487)：SwitchSession 持写锁先更换 activeSession，再调用 saveLocked，然后返回；SwitchToAgentSession（507）同样先改内存、保存再返回。
- [core/engine.go:7526](https://github.com/chenhg5/cc-connect/blob/dfad19415a38b00b2c5c288610784d1a7eef337f/core/engine.go#L7526)：cmdSwitch 清理旧交互状态，调用 SwitchToAgentSession，最后 reply 切换成功。因此该切换路径是先尝试同步保存，再响应，不是新建 goroutine 后立即回复。
- [core/session.go:735](https://github.com/chenhg5/cc-connect/blob/dfad19415a38b00b2c5c288610784d1a7eef337f/core/session.go#L735)：saveLocked 深复制、JSON 编码、AtomicWriteFile；失败只记录日志，不把失败返回给 switch 调用者。本项目遵从 Debug-First，SQLite 保存失败显式报错，不复制这个成功响应行为。
- [core/atomicwrite.go:20](https://github.com/chenhg5/cc-connect/blob/dfad19415a38b00b2c5c288610784d1a7eef337f/core/atomicwrite.go#L20)：临时文件 Write/Sync/Close 后 rename；rename 失败改直接写目标。这里只参考切换顺序与内存查询，不照搬该文件保存策略。其他 Save 调用和后台处理不能代表这个 switch 路径。

## 本项目选择及延迟

继续复用已有 aiosqlite（本身有 worker thread），改绑写锁串行，线程锁仅保护缓存读写、不跨 await；先更新内存，await SQLite commit 完成后响应。高频输入路由与发送前检查只读不可变 `{session_id, revision}`；实例改绑、解绑和回滚推进版本，改回同一 ID 也不会复活旧输出。

一次本机测量（10 次预热、100 次顺序真实 bind_instance commit，临时数据库）：Linux /tmp median 2.253 ms、P95 3.464 ms、max 4.217 ms；worktree 所在 /mnt/d median 5.766 ms、P95 6.801 ms、max 7.702 ms。只说明此次环境的低频写入成本，不作为性能 SLA，也不代表长历史或高并发请求数据库的性能。

因此没有新增后台 writer 的必要。新增 writer 将带来成功响应早于保存、失败反馈、关闭排空、顺序和重试的额外协议；用户最新决定接受简单方案。请求被取消时的短事务完成保护仍在原调用与写锁内等待，不是后台保存模式。真实 HTTP、并发写、提交失败、反复取消、重启恢复与 ABA 版本过期由测试覆盖。
