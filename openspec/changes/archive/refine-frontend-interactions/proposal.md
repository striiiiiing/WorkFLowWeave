# 修正前端交互与工作流调度

## Why

依据用户的[前端问题清单](../redesign-agent-channel-manager/前端问题修改.md)，当前工作流、资源、运行报告和 Agent 界面存在重复入口、配置状态位置不合理、模型选择冗余以及异步更新闪烁。Cron、话题命名和思考内容展示还需要真实后端契约支持。

本变更独立于 ChannelManager 后端重设计；其禁止前端修改的历史范围不扩写。本轮用户已明确要求实施前端清单。

## What Changes

- 精简总览与 Agent 重复入口，将高级选项、启用及保存操作移到对应上下文。
- 修正工作流模型选择与通知渠道复用，继续讨论优先使用有效默认模型。
- 工作流新增 Cron 和显式时区；旧秒间隔保留可观察的兼容路径，不做无法等价的转换。
- 统一报告与对话 Markdown 的主题和 AA 对比度；插件诊断归所属卡片。
- 支持话题命名、正确的消息分支和折叠思考内容；消除切换模型的整页重载与多余动画。

## Capabilities

### New Capabilities
- `frontend-interactions`: 页面操作位置、资源复用、默认模型、报告与 Agent 可用性。
- `workflow-cron`: Cron 校验、时区和到期调度、旧秒间隔兼容。

## Impact

Vue 正式页面及业务模块、共享主题，Python 工作流调度与 Agent 持久化/事件接口及其定向测试。既有 ChannelManager proposal/design 与用户原稿保留；不声称已验收或归档其他活动变更。
