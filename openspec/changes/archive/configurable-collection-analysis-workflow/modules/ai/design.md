# AI 模块设计

[总设计](../../design.md) · [接口契约](../../contracts/module-interfaces.md#4-ai) · [AIConfig](../../contracts/data-models.md#23-ai-配置)

AI 模块负责

1. 对系统提示词的处理
2. 对渠道进行管理，渠道有着相同的url和key，同时有着/v1/models的方法和启动和关闭，还有查看旗下有哪些模型。渠道暂时只支持OpenAI兼容渠道的服务，后继会添加其他的比如Response格式
3. 对LangChain的大模型调用进行封装，采用协程，同时提供采用关闭思考、和思考强度的选择，有low/medium/high/xhigh/max，同时设计取消的通知
4. 对于异常进行处理，包含错误报告和汇报错误全文


其目前对WorkFlow提供大模型服务
