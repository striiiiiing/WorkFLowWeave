# AI 模块设计

[总设计](../../design.md) · [接口契约](../../contracts/module-interfaces.md#4-ai) · [AIConfig](../../contracts/data-models.md#23-ai-配置)

AI 模块只完成一件事：用指定模型配置，对一份输入执行一个提示词任务，返回 AnalysisResult。Workflow 负责分支、调用次数、汇总和结果用途。

## 最小结构

`AIService` 提供 `validate` 和 `execute`；

同一模型渠道有着相同的 `base_url`、凭据，有着多个model及其配套的model_options。渠道可选择接口，区分为 OpenAI-compatible 接口、OpenAI-Response接口和Anthropic接口，本次只实现OpenAI-compatible 接口。

在应用时，需要设置timeout和retries，默认是600s和5次，理由是一般Workflow调用AI都是非流式的，可能需要思考很久，所以需要设置很久的timeout

该模块主要实现的是渠道管理部分

## 一次调用

采用LangChain的Model进行调用，采用异步调用


## 时限与失败

timeout 和 retries 默认 600 秒和 5 次。timeout 包含全部请求与重试等待，最多尝试 `1 + retries` 次

存储不是AI模块负责，这个模块是无状态的

## 验证要点

对于异常进行及时汇报