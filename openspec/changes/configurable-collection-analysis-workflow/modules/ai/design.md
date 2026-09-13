# AI 模块设计

[总设计](../../design.md) · [接口契约](../../contracts/module-interfaces.md#4-ai) · [AIConfig](../../contracts/data-models.md#23-ai-配置)

AI 模块只完成一件事：用指定模型配置，对一份输入执行一个提示词任务，返回 AnalysisResult。Workflow 负责分支、调用次数、汇总和结果用途。

## 最小结构

`AIService` 提供 `validate` 和 `execute`；一个普通 provider 映射选择 `mock` 或 `http` 适配器。`http` 表示 OpenAI-compatible 接口。提示词处理及结果映射可以是小函数，无需独立注册插件系统或执行图。

同一模型服务可保存多个 AIConfig，分别固定 `base_url`、凭据、model、system_prompt 和 model_options；“按模型服务渠道添加模型”通过这些可复用配置实现，与通知 Channel 无关。Provider 适配器经参数注入，业务逻辑不硬编码具体 SDK。

## 一次调用

1. 读取已传入的 AIConfig，按需解析 Credential，检查 provider、model、地址及已支持参数。
2. 仅对用户提示词做字面 `{input}` 替换；没有占位符时以两个换行附加完整输入。输入自身的花括号不递归展开，system_prompt 始终独立发送。
3. 调用异步 adapter，校验文本及错误响应，返回 task_id、status、text、usage、elapsed_ms；未提供用量时 usage 为空对象。

`model_options` 支持适配器已声明的思考开关/强度和其他请求 JSON 参数，未经声明的参数报错；不得覆盖 messages、model、认证、地址或执行预算，拒绝 temperature 和 top_k。

## 时限与失败

timeout 和 retries 仅来自 AIConfig，默认 60 秒和 0 次。timeout 包含全部请求与重试等待，最多尝试 `1 + retries` 次；SDK 自带重试关闭，避免叠加。只重试确认未成功的暂态失败，配置、认证和协议错误立即报告。取消后不再发起请求，输出 cancelled。

服务不维护会话记忆、工具调用、Agent 循环或 LangGraph，也不持久化输入输出。资源清理由适配器和装配层负责，独立调用不要求 session。

## 验证要点

检查占位符、系统角色隔离、请求参数映射、重试总时限、取消，以及模型错误未被当成成功文本。Mock 与 http 使用相同结果契约。
