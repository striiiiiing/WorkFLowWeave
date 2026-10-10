# 过度防御与兼容收敛

依据：用户 2026-10-08 要求修复审查报告 F1、F3–F6、W1、W2，排除 F2；用户进一步明确 Collector/Setter 没有历史数据，直接删除相关实现与描述，不建立旧数据拒绝或迁移边界。旧 tasks.md 中有关 Collector/Setter 历史资源的假设由本次明确指令取代；不修改 proposal.md 或 design.md。

这是结构修正：来源配置、调用解析、插件发现、快照与前端只表达 MCP/CLI 一个契约。来源默认超时 60 秒、on_error/on_empty 默认 notice 沿用当前模型；MCP 零计数不进入 on_error，依据 redesign-mcp-schema-first/design.md 第 5–6 节。schema、快照身份与版本校验仍是必要边界。

- [x] F1：删除 Collector/Setter 模型、资源类型、合并/执行分支、注册体系及无数据依据的历史边界；测试改用实际 MCP/CLI 契约。
- [x] F3：discover 只在明确方法缺失时回退，分页不重复探测；鉴权、实现和响应格式错误显式失败。
- [x] F4：SSE generation 只保护订阅，GET 由会话、取消与当前请求身份保护，仍比较快照版本。
- [x] F5：当前轮次的持久化 message.delta 是唯一发布事实；取消、超时、错误回读同一事件日志，不额外维护布尔状态。依据 EventLog.append 的持久化边界和 run_blocking_owned 的取消语义：worker 完成提交后仍可能传播取消，单纯 await 后设置标志会漏记已提交增量。
- [x] F6：删除无消费者的 queue 别名、create_graph 入口、Telegram 不可达 missing_ok 分支。
- [x] W1：持久化资源/运行快照读取时将 http 归一为 openai_compatible_api，校验、装配和 UI 只用正式 ID。不再支持新前端对旧后端写回别名。
- [x] W2：删除编辑器 retention_days 提示/确认/转换分支；归档期限继续按保存事实读取，依据 redesign-workflow/design.md 第 8 节及用户本轮修复范围。
- [x] 定向回归、静态检查、构建、最小烟测与 diff 复核；更新审查报告完成状态。

F2 的 MCP JSON 新建/编辑转换保持本次范围之外。未引入默认值、隐式重试或吞错降级。

## 实施依据

- 来源执行契约以 `redesign-mcp-schema-first/design.md` 和本变更的 collection/agent-interface specs 为准：`SourceConfig.call` 必填，MCP/CLI 是唯一来源形态。用户明确没有需要保留的 Collector/Setter 历史数据，因此不增加拒绝、只读或迁移分支。
- `server/discover` 只在明确的 `METHOD_NOT_FOUND`（以及 SDK transport 对已确认未知请求签名的精确归一）时回退 `tools/list`；普通参数、鉴权、实现和响应 schema 错误必须失败。默认来源超时继续使用现有模型的 60 秒，不新增重试。
- Agent partial 以已持久化的 `message.delta` 为唯一事实。`EventLog.append` 可能在调用方收到取消前完成写入，因而不能用易失布尔值推断发布状态；取消、超时和异常统一回读本轮事件。
- provider `http` 只在持久化资源/运行快照读取边界归一为正式 `openai_compatible_api`，归一结果原子写回；运行校验、factory 和 UI 不再接受别名。retention 编辑器只表达四类当前期限，已有归档截止日期仍由存储层按事实读取。

## 验证记录

- `tests/mcp/test_runtime.py tests/mcp/test_health_monitor.py tests/workflow/test_mcp_cli_flow.py`: 26 passed，包含真实 stdio、discover 回退、错误 schema 和参数错误边界。
- 配置/采集/集成分组 322 passed；Agent/渠道分组 70 passed；生命周期/API 分组 78 passed；进程强退恢复 4 passed；工作流恢复选定集 44 passed。
- Agent 流式失败、取消、空闲/总超时及持久化取消窗口 37 passed；前端定向回归通过，`vue-tsc --noEmit`、架构检查、Vite build、Python compileall、ruff（忽略既有 I001 import 排序）和 `git diff --check` 通过；Python wheel 构建成功。
- 本地 AI HTTP 端点返回鉴权失败，未把该真实外部依赖改成 mock 或跳过；F2 未修改。
