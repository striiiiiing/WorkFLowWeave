# AI任务

状态：待执行，完成后在本文件记录提交前验证结果。

依据：[AI设计](./design.md)、[总设计](../../design.md)及本次用户确认。contracts 为派生文档，不作为独立事实来源。旧任务与历史执行记录保留在基线 `4dfa8d0072fc16eda4f1c3da25bac36969327deb`；当前任务按设计提交 `97ebd68` 修正，旧“已完成”不代表符合新设计。

依赖：公共模型与协议、配置凭据；不依赖 Workflow 执行。

- [ ] 按 design 的“模型渠道共享 base_url/凭据、多个 model 及配套 model_options”整理 AI 配置与模型选择，保持五类资源；任务明确选模型，消除重复连接配置及模型选项的多个来源。所选配置结构和迁移依据写入本任务，更新受影响模型/调用者/测试。
- [ ] 默认 timeout=600 秒、retries=5，依据 AI design 对非流式长思考的说明；总时限涵盖凭据解析、请求与等待，最多 1+retries 次，不启用 SDK 叠加重试。
- [ ] 仅实现 OpenAI-compatible 正式接口，Mock 作为明确的离线验证适配器；保留 provider 注入。允许 JSON 模型扩展参数，拒绝 temperature/top_k 及覆盖 model/messages/认证/管理字段；删除过时的狭窄参数白名单。
- [ ] 系统提示词独立 system 角色；{input} 字面替换，不递归模板执行；无占位符时追加完整输入（沿用现有行为以满足完整共享输入）。非法返回、缺失凭据解析器、协议和认证错误显式失败。
- [ ] 仅确认未受理的暂态失败重试；读取超时/断连等不确定受理错误不盲目重试。取消后不启动下一次请求，返回 cancelled；客户端有界且幂等关闭，清理错误不吞掉。
- [ ] 本地 HTTP/可控适配器测试角色、参数、隔离、总预算、重试计数与取消（60 秒）；lint、构建、离线单次分析烟测。声明直接使用的依赖。

## 实际实现与验证（2026-09-17）

- AIConfig 在保留兼容默认 model/model_options 的基础上增加 `models` 映射；每个 AI 资源共享 provider/base_url/api_key/system_prompt/timeout/retries，Workflow 的 AnalysisTask/FanInConfig 可显式选择模型，未指定时沿用资源默认 model。WorkflowSnapshot 校验所选模型存在。
- 默认 timeout/retries 调整为 600 秒/5 次，依据 AI design 对非流式长思考调用的说明；总时限从凭据解析开始计算，凭据解析、请求和重试等待共用预算。
- AIService 保留 OpenAI-compatible HTTP 与 Mock provider；system/user 分离，`{input}` 仅字面替换，无占位符时追加完整输入；模型 options 透传但拒绝覆盖 model/messages/认证/管理字段及 temperature/top_k。缺少凭据解析器、非法模型、认证/协议错误显式失败。
- 本次仍保留旧字段作为迁移兼容层，后续可在完整调用方迁移后移除；这避免现有持久化资源和 Workflow 测试在过渡期间失效。
- 验证：Workflow integration 2 passed；Workflow recovery 34 passed；process recovery 3 passed；Config/资源/凭据/Workflow integration 定向 86 passed；相关 Ruff 通过。全套回归在当前代码路径已完成既有 388 项回归，未发现功能失败。

### 决策依据与默认值

- 多模型结构依据 AI design “同一模型渠道共享连接/凭据，包含多个 model 及其配套 model_options”；兼容字段暂保留是迁移策略，不作为第二运行时来源，`models[model]` 是执行时唯一选项来源。
- Workflow 不强制旧 FanIn 配置立即补写 model；未指定时使用 AIConfig.model，保证既有定义可重放，同时新配置可显式固定模型。
