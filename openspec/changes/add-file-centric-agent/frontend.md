# Agent 前端设计

前端使用现有 Vue 3、Element Plus、Tailwind、Vue Router、报告组件和 Schema 表单组件。首版后端是项目自己的 FastAPI SSE，因此由前端维护一个小型 `useAgentStream`；不能把普通 SSE URL 直接传给 `@langchain/vue` 的 `useStream`。如果后端以后实现 LangGraph Streaming Protocol v2，再通过 `AgentServerAdapter` 接入官方 transport，不迁移页面结构。

## 1. 页面和入口

导航增加 Agent，路由为 `/agents` 和 `/agents/:sessionId`。桌面端显示会话/分支树、聊天区和按需详情抽屉；窄屏保持单列聊天，会话、来源、文件和设置改为抽屉。

```text
┌──────────────┬─────────────────────────────────────┐
│ ＋ 新会话     │ 日志排查   来源 Workflow ▾  模型 ▾   │
│ 今天          │ 分支 main · 沙箱开启 · 上下文 68%    │
│  · 日志排查   ├─────────────────────────────────────┤
│  · 异常复盘   │ 用户：继续分析这次运行                 │
│   └─ 分支     │ ▸ Collector · 排队/运行/完成           │
│               │ Agent：……                             │
│               │ ── 已压缩早期上下文 · 查看摘要 ──       │
│               ├─────────────────────────────────────┤
│               │ 输入…                  发送 / 停止      │
└──────────────┴─────────────────────────────────────┘
```

Workflow 详情页增加“从最新结果继续”和历史运行的“继续讨论”。创建时展示来源 Workflow session、结果时间和可选模型；来源绑定只读。Workflow 后续完成新运行时，只刷新历史列表，不替换 Agent 当前上下文。

## 2. 消息、命令和分支

助手文本按 SSE 增量显示，完成后使用安全 Markdown 渲染；禁用 HTML 和危险链接协议。工具卡片显示工具名、Collector ID、排队/运行/完成/失败、耗时、短结果和 Artifact 引用；参数、Schema、诊断和完整输出在展开区。Channel 只显示当前绑定的 channel/session，不显示可任意选择的投递目标。

输入区提供停止、`/compact`、`/append`、`/fork` 和会话命令入口。状态优先级显示为 `stop > command > conversation`：

- 运行中 `/compact` 和 `/append` 显示“已排队，将在工具组完成后的模型边界处理”。
- 空闲 `/compact` 立即执行；空闲 `/append` 创建一轮新的用户输入。
- 停止要等后端确认终态；已经完成的写入或外部副作用不显示撤销。

分支树显示 `branch_id`、父节点和当前叶子。编辑用户消息先创建分支预览，确认后提交新分支；父分支、模型输出、工具参数和工具回执只读。切换分支不修改旧树。checkpoint 缺失或损坏时，页面显示不可继续原因和可读事件文件入口，不提供可能重放副作用的“重试整轮”。

## 3. Workflow、文件和工具面板

来源抽屉展示 Workflow session、最终输出对象预览、绑定模型和创建时间。文件抽屉提供：

| 内容 | 展示与编辑 |
| --- | --- |
| `AGENTS.md` | 普通文本编辑；显示“下一轮生效”和版本。 |
| `Memory/YYYY-MM-DD.md`、`History/<session>.md` | 可编辑；保存携带 ETag/If-Match。 |
| `Runtime/History/.../events.jsonl`、`summaries/` | 只读事实和摘要，显示时间、覆盖范围、完整性。 |
| `Runtime/Artifacts/` | 按工具调用分页读取，标注截断、缺失和大小。 |
| `Runtime/Catalog/` | 只读插件目录和调用 Schema，不作为账号配置入口。 |

文件保存冲突保留用户草稿，提供重新读取或合并入口。前端不自行推断工具执行类别，以 `GET /api/agents/tools` 的后端状态为准。

工具面板显示实际启用的插件、工具 generation、执行类别和 Schema/定义 Token 估算。关闭 `read/write/grep/shell` 后显示真实剩余能力；Shell 关闭不隐藏 Collector。插件 reload 忙时显示“等待当前轮结束”，不能在活动轮中替换工具定义。

## 4. 上下文、压缩和事件流

顶部显示有效 context limit、输出预留、当前完整请求用量、90% 触发线和“实际值/估算”标签。默认值显示为 `C=200,000`、`R=4,096` 和按固定 system/AGENTS/tools 开销计算后的消息预算；模型或配置覆盖时显示来源。未知模型容量要求用户配置，不显示猜测值。

收到 `context.compacted` 时，聊天区显示轻量分隔条、摘要和被覆盖事件范围；旧消息不从 UI 删除，可从 Runtime 历史查看。摘要失败显示明确错误、保留原上下文和可读的下一步，不显示压缩成功。

`useAgentStream` 使用事件 `id` 作为游标：

1. 连接时读取 `after`/`Last-Event-ID` 之后的缺失事件；
2. 在同一游标边界接入实时订阅；
3. 按 ID 去重，再更新消息和工具卡片。

断线不取消后台轮次。心跳不写历史；慢客户端只暂停渲染，不阻塞服务端工具。`tool.queued`、`tool.started`、`tool.completed` 按 `tool_call_id` 更新同一张卡片；读并发按组折叠，写操作显示工作区独占等待，重启中断显示为状态事件。

## 5. 设置

设置抽屉包含：

1. Provider/模型、上下文容量、输出预留、摘要模型和摘要 Prompt 版本；
2. 五个内置工具插件及其他可用 tool 插件的开关、实际 Schema 和定义 Token 估算；
3. `sandbox.enabled`、`sandbox.network` 和 bubblewrap 可用性；
4. 工作区只读路径和每日 Memory 的 IANA 时区。

沙箱关闭显示“按服务进程权限运行”；沙箱不可用显示“隔离启动失败”，两者不能混淆。运行中的一轮固定模型、工具 generation、AGENTS 和提示模板版本；设置变更从下一轮生效。

## 6. 客户端和组件

建议新增：

- `AgentView.vue`：页面布局和会话入口；
- `AgentTranscript.vue`：消息、Markdown、压缩分隔；
- `AgentBranchTree.vue`：树形分支和叶子切换；
- `AgentToolCall.vue`：工具状态、参数、结果和 Artifact；
- `AgentFileDrawer.vue`：目录、分页读取、编辑和冲突；
- `AgentSettings.vue`：模型、工具、沙箱和预算；
- `useAgentStream.ts`：SSE 生命周期、回放、去重和事件归并；
- `api/agents.ts`：会话、命令、文件、配置和工具 API。

复用 PageHeader、SectionCard、StatusBadge、ParameterField、报告渲染和安全 Markdown 组件。页面不实现第二套 JSON Schema 验证、权限判断或读写调度。

## 7. 验收

使用临时工作区和 mock Collector 验证：

- Workflow 结果续接、最新入口、模型切换和绑定来源；
- 命令优先级、运行中 `/compact`/`/append` 排队、停止和分支编辑；
- 并行读取、写等待、工具关闭、插件 reload 和沙箱关闭/不可用；
- AGENTS 下一轮生效、Memory/History 编辑、ETag 冲突和 Runtime 只读；
- 长上下文压缩、摘要失败、旧消息保留、checkpoint 中断；
- SSE 续传不漏不重、慢客户端和浏览器刷新；
- 安全 Markdown、窄屏布局和真实本地后端 SSE 烟测。

自动化测试不连接真实渠道或发送邮件；浏览器烟测必须进行真实 MCP/HTTP 工具调用或真实本地 SSE 连接，不能只启动服务就算通过。
