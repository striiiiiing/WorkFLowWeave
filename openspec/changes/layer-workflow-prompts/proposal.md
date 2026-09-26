# 分层 Workflow 提示词

## Why

当前 Workflow 的系统提示词保存在 AI 资源上，分析项与 fan-in 各自只有一个输入模板；它不能表达“默认同步、单项覆盖”的系统提示词，也不能把带 `{input}` 的用户内容与每项差异指令分开。远端 `workflowServer` 已有 `user_prompt` 和 fan-in 复用能力，本次要求在其基础上调整消息结构。

## What Changes

- Workflow 保存共享系统提示词和带 `{input}` 的共享用户输入模板；分析项及 fan-in 可覆盖系统提示词，并配置各自的差异用户指令。
- 模型请求将系统、输入、差异指令按顺序作为独立消息；fan-in 的输入包含按配置顺序选择的原始输入与前一步分析结果。
- 采用远端 fan-in 的模型复用和顺序规则；已有工作流的提示词在显式迁移后保持原执行含义。
- 前端编辑器提供同步默认值、逐项覆盖和汇总配置。

## Capabilities

- `workflow-prompts`：可配置、可复用且顺序确定的工作流提示词消息。

## Sources

- [任务要求](../backendFix/任务要求.md)
- `ssh myserver:~/opt/workflowServer` 的 `AnalysisTask.user_prompt`、`FanInConfig.reuse_from`、`FanInConfig.ordered_inputs` 和 AI 请求组合实现。
