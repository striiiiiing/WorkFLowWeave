# Agent 会话上下文入口记录

## 问题

`Runtime/Session/<session_id>.json` 不能作为模型发现自身 ID 的首个入口，因为路径本身要求模型已经知道 `session_id`。共享工作区若增加 `Runtime/current.json`，多个 Agent 会话并发时还会发生覆盖和串读。

## 决策与依据

| 决策 | 依据 | 结果 |
| --- | --- | --- |
| 使用 `Runtime/self.json` | 用户要求 Linux 式可读文件；`self` 表达进程/会话作用域，不要求预先知道 ID | 模型固定 `read("Runtime/self.json")` 获取自己的 session、turn、branch、来源 Workflow、模型和工具 generation。 |
| `self.json` 是逻辑映射，不是共享物理文件 | 多个 Agent 可以同时运行；共享 `current.json` 会产生竞态 | `WorkspaceBackend` 绑定当前 Agent 会话快照，按调用方解析同一路径；不落盘、不由模型写入。 |
| 保留 `Runtime/Sessions/<session_id>.json` | UI 和已知 ID 的历史查看仍需要稳定持久路径 | 它是只读持久元数据视图；当前会话发现使用 `self.json`，不依赖该路径。 |
| 提示词只提供路径说明 | 运行元数据的事实应来自文件，避免系统提示和文件各维护一份 ID | AGENTS 默认说明如何读取 `Runtime/self.json`，不直接硬编码当前 session 值。 |

## 验证要求

- 两个并发 session 分别调用 `read("Runtime/self.json")` 时，返回各自 `session_id`，不能互相覆盖。
- `Runtime/self.json` 只能读取，write/grep 不得把它当作普通持久文件修改或搜索出其他 session 的内容。
- `Runtime/Sessions/<session_id>.json` 与事件/会话元数据使用同一事实来源，不新增独立 current 状态表。
