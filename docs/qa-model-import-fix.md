# 全功能联调发现的模型导入问题

## 问题与根因

2026-10-06 的真实前端验收进入 `/agents` 时，Vite 显示 `Failed to resolve import "../model/events" from "src/modules/agents/langchain/stream.ts"`，Agent 页面无法挂载，后续交互测试受阻。

前端 Model 按业务子域迁移后，Agent SDK adapter/stream、消息组件和命令 composable 仍引用已删除的根模型路径；部分测试也保留旧路径。Workflow 默认值中的 `cronPresets` 引用同样未随迁移更新。

## 修改方案与依据

依据 `openspec/changes/redesign-frontend-modules/design.md` 与该 change 的 `tasks/2026-10-06-frontend-modules/task.md`：模型归属迁至 `agents/model/{session,runtime,workspace}` 和 `workflows/model/create`，消费层只做必要导入适配。

- Agent 事件解析、会话投影、transcript 和公共值类型均引用已有纯模型出口 `model/public`，该出口提供 `model/runtime` 的唯一实现；与用户指定的远端修复一致，便于后续合并。
- Workflow 的旧根 `model/types.ts` 与 `model/defaults.ts` 已无消费者，内容与新模型重复；删除两份遗留实现，默认值与类型继续由 `model/create` 和 `model/public` 唯一提供。此前仅改 `cronPresets` 导入仍会保留重复实现，不能解决根因。
- 相关单测同步引用实际模型归属，不增加旧路径兼容层或复制实现。

本次保持原协议、业务逻辑与默认值；不修改 proposal/design。工作区已有的其他未提交修改保留。

## 验证

原始故障证据：`/tmp/logagent-tabbit-qa/report-agent-r3.md`。用户随后要求暂停有头浏览器，修复后的真实 UI 回归由 GPT 6 Luna 子代理使用无头浏览器执行；单测、类型检查、构建与回归结果待验收完成后补充，不将尚未执行的检查记为通过。

架构检查进一步报告 `modules/workflows/model/types.ts: model-purity: @/modules/resources/public`。遗留类型文件依赖包含 API/UI 的业务出口，而新模型使用纯模型出口。删除无引用旧实现以恢复迁移设计中的单一类型和默认值归属；没有放宽架构规则或增加兼容转导。

当前已完成的修复验证：

- Agent adapter/protocol/stream 与 Workflow Agent task 定向单测：4 文件、18 项通过。
- `npm run typecheck` 通过；`npm run build` 通过，Vite 处理 4,223 个模块。构建仅有依赖 Zod 注释位置警告。
- 删除旧模型文件后 `npm run architecture:check`：202 个源文件和 44 个正反 fixtures 通过。
- 无头 Agent 子代理已通过真实可见导航进入 Agent 主界面；未再观察到旧导入错误覆盖层。Mock 会话等完整功能回归仍在进行，不将这项页面证据扩展为所有功能通过。
