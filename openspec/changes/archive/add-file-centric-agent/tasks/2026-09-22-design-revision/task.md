# 2026-09-22 设计修订任务

## 范围

本任务记录用户改写 `design.md` 后的统一决策，不修改旧实施历史，不把本轮文档整理当作代码验收。基线提交为 `65d600e`。

## 决策与依据

| 决策 | 设计依据 | 选择理由 |
| --- | --- | --- |
| 保留五个模型工具 | design §4 用户原始“五个”方案；Codex/Claude 的短工具参考 | `plugin` 聚合 Collector；Runtime 用可读文件，不增加第六个工具。 |
| plugin 只调用 Collector | design §2/§4 对 Channel 发送的疑问；Channel 是绑定的双向路由 | 防止模型绕过会话路由向任意目标发送；Workflow 通知继续复用 ChannelManager。 |
| CLI/HTTP/Agent 共用 application service | design §2 Collector CLI/HTTP 意见 | CLI 是运维和 Shell 适配，Agent 直接调用服务，避免持写锁后回调 HTTP 死锁。 |
| 工作区级而非模型级锁 | design §5 对全局 Agent 锁的担忧；Codex/Claude 并行主要依赖 worktree | 单工作区的写入仍必须串行，但跨会话模型生成和读操作可并行；未来独立 worktree 另立设计。 |
| 200,000/180,000/40,000 | design §8 用户明确默认 200k、90%；LangChain middleware 支持 token trigger/keep | 采用固定 message 粒度，不引入旧的自适应比例；未知容量要求配置。 |
| `trim_tokens_to_summarize=None` | LangChain 摘要源码默认 4,000 且存在 fallback | 避免摘要前静默裁掉早期消息；摘要输入容量不足时明确失败。 |
| AGENTS/工具/prompt 按 turn 捕获 | design §7/§8 的 prefix cache 要求；Claude prompt caching 与 Codex AGENTS 文档 | 活动 turn 内保持稳定，文件修改下一轮生效，压缩不删除常驻前缀。 |
| thread 保留整条 checkpoint 链 | LangGraph `AsyncSqliteSaver` 3.1.1 公开支持整条 thread 删除，但没有可安全依赖的中间 prune；DeltaChannel 需要 ancestor 链 | session/thread 元数据保存 `created_at`、`updated_at`、`last_checkpoint_at`；只在显式保留策略、过期、无活动/分支/Artifact 引用时整条删除。普通 compact/fork 不删中间行。 |
| Pi 式事件树与 LangGraph update 分支 | Pi JSONL `id/parentId`；LangGraph `Pregel.update_state` 可从 checkpoint 建分支 | 编辑用户输入创建新 branch，模型输出只读，原树保留。 |
| 自建 Vue SSE 首版 | `@langchain/vue` 需要 Agent Streaming Protocol；当前 FastAPI SSE 尚未对齐 | 先实现小型事件游标/重连适配；协议对齐后再接官方 Vue hooks。 |
| 系统本地时区、显式配置优先 | design §7 用户修订 | 便于按日 Memory 与用户理解；不使用旧 UTC 默认。 |

## 验收时必须证明

- Collector 参数 Schema、凭据和调用状态仍来自现有公共解析/Manager；每个 call 只有一次外部调用。
- 工具开关不导入、不注册、不进入模型 tools；Shell 关闭不影响 Collector。
- 两个会话可以同时生成/读取，工作区写入和 Shell 独占；取消/异常释放锁。
- `created_at`/`updated_at` 在事件和 checkpoint 提交时更新；清理不会删除被分支或 Artifact 引用的 thread，也不执行私有 SQLite 删除。
- `/compact`、`/append` 在下一次模型返回边界处理；自动压缩每次请求最多一次，失败保留旧上下文。
- Workflow 新运行不切换已有 Agent；fork 不修改旧模型输出；SSE 断线按事件 ID 去重。
