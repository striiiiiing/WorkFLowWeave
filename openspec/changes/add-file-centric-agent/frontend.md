# Agent 前端设计

前端继续使用当前 Vue 3、Element Plus、Tailwind、Vue Router 和既有报告/Schema 组件。LangGraph 官方提供 `@langchain/vue` 的 `useStream`、消息和工具调用组件，但它要求 LangGraph Agent Streaming Protocol；现有 FastAPI SSE 不能直接当作即插即用的 Vue 组件。因此首版由 Vue 自己消费本设计的事件信封，后续若后端对齐官方协议，再以适配层替换流式实现，不迁移整个页面。

## 1. 入口与布局

导航增加 Agent，路由为 `/agents` 和 `/agents/:sessionId`。左侧显示会话和分支树，中间是聊天，右侧抽屉按需展示 Workflow 来源、工具、文件和设置。窄屏只保留聊天，会话、文件和设置改为抽屉。

```text
┌──────────────┬─────────────────────────────────────┐
│ ＋ 新会话     │ 日志排查   来源 Workflow ▾  模型 ▾   │
│ 今天          │ 分支 main · 沙箱开启 · 上下文 68%    │
│  · 日志排查   ├─────────────────────────────────────┤
│  · 异常复盘   │ 用户：继续分析这次运行                 │
│   └─ 分支     │ ▸ 采集 Collector · 运行中/完成         │
│               │ Agent：……                             │
│               │ ── 已压缩早期上下文 · 查看摘要 ──       │
│               ├─────────────────────────────────────┤
│               │ 输入…                  发送 / 停止      │
└──────────────┴─────────────────────────────────────┘
```

Workflow 详情页增加「从最新结果继续」和每个历史运行的「继续讨论」按钮。创建时显示来源 Workflow session、结果时间和可选模型；来源之后保持只读绑定。Workflow 新运行完成只更新历史列表，不替换当前 Agent。

## 2. 消息、命令与分支

助手文本按 SSE 增量显示，完成后再做完整 Markdown 渲染；HTML 禁用，危险链接协议过滤。工具卡片只显示动作、Collector ID、排队/运行/完成/失败、耗时和短结果，Schema、参数、Artifact 和诊断在展开区。渠道来源显示绑定的 channel/session，不显示一个模型可任意选择的发送目标。

输入框旁提供停止、`/compact`、`/append`、`/fork` 命令入口；命令状态按 `stop > command > conversation` 展示。运行中提交普通消息进入后端准入规则，`/compact` 和 `/append` 显示“将在下一次模型返回后处理”。停止完成后才显示终态，已经完成的写入或外部副作用不显示撤销。

分支树显示 `branch_id`、父节点和当前叶子。编辑用户消息必须创建分支预览，确认后提交新分支；原用户消息、模型输出和工具结果只读。切换分支不会修改旧树。会话恢复失败时展示 checkpoint 缺失/损坏和可读事件文件入口，不提供可能重放外部副作用的“重试整轮”按钮。

## 3. Workflow、文件与工具

来源抽屉显示 Workflow session、最终输出对象的可读预览和绑定模型。文件抽屉提供 `AGENTS.md`、`Prompts/summary.md`、`Memory/`、`History/`、`Runtime/`、`Artifacts/`、只读 `Catalog/`；Runtime/session 和 workflow 文件帮助用户检查来源与当前分支。

| 内容 | 展示与编辑 |
| --- | --- |
| `AGENTS.md`、`Prompts/summary.md` | 普通文本编辑；提示下一轮生效，并显示版本/上下文占用。 |
| `Memory/YYYY-MM-DD.md`、`History/<session>.md` | Agent 与用户共享同一 ETag/If-Match 写入边界。 |
| `Runtime/History/.../events.jsonl`、`summaries/` | 只读原始事实/摘要，标注时间、覆盖范围和是否完整。 |
| `Runtime/Artifacts/` | 按工具调用分页读取完整输出，标注截断/缺失。 |
| `Runtime/Catalog/` | 只读插件列表和调用 Schema，不作为账号配置入口。 |

文件保存冲突保留用户草稿并提供重新读取/合并选项；前端不自行推断工具执行类别，后端状态为准。关闭 read/write/grep/shell 后，工具面板显示真实剩余工具；Shell 关闭不隐藏 Collector，沙箱关闭显示“按宿主权限运行”，沙箱不可用显示“隔离启动失败”。

## 4. 上下文、压缩与事件流

顶部展示有效 context limit、当前完整请求用量、90% 阈值和“实际值/估算”标签。默认值是 200,000/180,000；模型或配置覆盖时显示覆盖来源。压缩产生轻量 `context.compacted` 分隔条，可展开用户可编辑的摘要和覆盖事件范围；聊天旧消息不删除。

SSE 使用后端事件 `id` 作为游标。`useAgentStream` 先回放 `after` 缺失事件，再在同一个订阅边界接入实时事件，按 ID 去重；断线不取消后台运行。心跳不写入历史。慢客户端只暂停渲染，不阻塞服务工具。

当收到 `tool.queued`、`tool.started`、`tool.completed` 时，按 `tool_call_id` 更新同一张卡片；并行读取按组折叠，写操作显示工作区独占等待。命令队列、checkpoint 清理和重启中断均显示为状态事件而非模型消息。

## 5. 设置

设置抽屉只包含：

1. 已配置 Provider/模型、上下文容量、输出预留、摘要模型和 `Prompts/summary.md` 版本；未知模型容量要求用户填写。
2. 五个工具插件开关和实际 Schema/定义 Token 估算；启停在插件配置重载后对下一轮生效。
3. `sandbox.enabled`、`sandbox.network`、bubblewrap 可用性；不可用与关闭严格区分。
4. 工作区只读路径和每日 Memory 时区；默认系统本地时区，显式 IANA 配置优先。

运行中的一轮固定模型、工具 generation、AGENTS 和提示模板版本；设置变更不改变当前 prompt 前缀。

## 6. 组件与验收

建议新增：`AgentView.vue`、`AgentTranscript.vue`、`AgentBranchTree.vue`、`AgentToolCall.vue`、`AgentFileDrawer.vue`、`AgentSettings.vue`、`useAgentStream.ts`、`api/agents.ts`。复用 PageHeader、SectionCard、StatusBadge、ParameterField、报告渲染和安全 Markdown 组件。

验收用临时工作区和 mock Collector 覆盖：Workflow 结果继续、最新入口、模型切换、双向命令队列、并行读/写等待、分支编辑用户消息、无法修改模型输出、压缩后历史保留、摘要失败、checkpoint 中断、SSE 续传去重、文件 ETag 冲突、工具关闭、沙箱关闭/不可用和手机布局。真实渠道不发送；浏览器烟测必须连接真实本地 SSE。
