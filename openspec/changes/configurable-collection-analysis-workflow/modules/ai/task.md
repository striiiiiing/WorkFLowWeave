元信息
- 关联规范：[总设计](../../design.md)、[AI 模块设计](./design.md)、[数据模型 §2.3、§4.3、§6](../../contracts/data-models.md)、[模块接口 §4](../../contracts/module-interfaces.md)。
- 任务总数：5。
- 预计执行时间：约 4.5 小时人工开发时间；单任务 45–75 分钟，适配器与提示词工作可并行。

执行范围：AI 不是 collection 的前置依赖，本轮只规划，全部任务留待后续 AI 模块实现。以下任务均未执行，不表示已具备模型调用能力。

依赖执行：公共契约 → Task 1；Task 2 与 Task 3 可在 Task 1 后并行；Task 4 等待 Task 2、Task 3，Task 5 完成集成和清理。AI 不依赖 Workflow/LangGraph 的实现，独立调用不要求 session。

## 执行记录（2026-09-15）

- 已完成：实现 `AIService.validate/execute`、离线 Mock provider、OpenAI-compatible HTTP provider、字面提示词组装、usage 映射、总时限、有限重试、取消和客户端关闭。
- 已完成：AIService 本身保持单次调用语义，凭据仅在调用期间解析；Workflow 将分析输入、输出和脱敏错误写入 SQLite，并在恢复时复用成功分析项。

# Task 1: 定义 AI 配置验证与适配器边界

描述：后续 AI 模块任务，预计 45 分钟。建立 AIService.validate 和可注入的 mock/http 适配器映射，明确支持的模型参数及资源配置边界。

输入：contracts.AIConfig、contracts.AnalysisResult、contracts.ExecutionContext 和受支持 provider/模型参数声明。

输出：ai.AIService.validate、异步 Provider 适配器协议及明确的参数白名单。

依赖：公共 AI 配置、Credential、ErrorInfo 和分析结果契约。

验收标准：
- provider 仅接受当前支持的 mock/http；model 非空，http 地址合法，timeout 为正有限秒数，retries 为非负整数且不接受布尔/字符串隐式转换。
- 顶层及 model_options 均拒绝 temperature、top_k；不允许覆盖 messages、model、认证、地址、timeout 或 retries。
- 已声明的思考开关/强度等扩展按适配器规定校验，未知参数返回字段级原因，不直接透传任意 JSON。
- validate 不发起模型请求、不解析凭据造成外部调用，且不修改传入配置。

# Task 2: 实现提示词组装与离线单次执行

描述：后续 AI 模块任务，预计 45 分钟。实现提示词安全的字面替换、角色隔离、Mock 适配器和统一成功/失败结果映射。

输入：AIConfig、prompt、input_text、task_id 及可选 ExecutionContext。

输出：ai.AIService.execute 的单次执行路径、Mock 适配器及标准 contracts.AnalysisResult。

依赖：Task 1。

验收标准：
- 所有字面 {input} 都替换为完整输入；无占位符时用两个换行追加输入，输入中的花括号不递归展开。
- system_prompt 始终以独立系统角色传递，用户提示词与输入不能改变它的角色或创建新配置。
- 结果保持调用方 task_id，elapsed_ms 为非负有限数值；未提供用量时 usage 为独立空对象，不编造 token 数量。
- Mock 和真实适配器共用成功/失败语义，异常或非法响应不被包装为成功分析文本；独立调用可不传 session。

# Task 3: 实现 OpenAI-compatible HTTP 适配器

描述：后续 AI 模块任务，预计 75 分钟。通过可注入异步 HTTP 客户端调用配置中的服务，按需解析 Credential，并验证请求与响应协议。

输入：Task 1 的请求边界、AIConfig.base_url/model/model_options、系统/用户消息和 config.CredentialManager.resolve。

输出：ai 的 http Provider 适配器、协议错误分类和服务端 usage 映射。

依赖：Task 1；config.CredentialManager.resolve；不依赖 Task 2 的提示词实现，可用固定消息独立开发。

验收标准：
- 请求只使用传入配置的地址、模型、凭据和已声明参数；服务管理字段不能被 model_options 覆盖。
- 客户端自带重试关闭，异步调用可取消；网络资源释放有明确入口，不创建无所属后台任务。
- 认证失败、非成功响应、非法 JSON、错误 envelope 或缺少有效文本均产生可识别失败，不将错误响应正文作为分析结果。
- 使用本地模拟 HTTP 服务验证参数和角色映射、正常文本及 usage、协议错误；验证不请求真实付费模型。
- 凭据仅用于运行时认证，不出现在日志、错误信息、配置返回值或结果 metadata。

# Task 4: 实现整次调用时限、重试与取消

描述：后续 AI 模块任务，预计 60 分钟。由 AIService 为全部请求和退避等待使用一个总预算，落实保守重试与取消语义。

输入：Task 2 的执行流程、Task 3 的错误分类及 AIConfig.timeout/retries。

输出：包含统一截止时间、有限尝试次数和 cancelled/timeout 结果的 ai.AIService.execute。

依赖：Task 2、Task 3。

验收标准：
- 总尝试次数不超过 1 + retries，timeout 覆盖全部请求和等待；重试不会重置剩余时间。
- 只对确认未成功且暂态的错误重试；配置、认证及不可重试协议错误首轮即返回失败。
- 总预算耗尽返回 timeout，不将部分或未完成响应视为成功；elapsed_ms 包含重试和等待时间。
- 取消后返回 cancelled，等待中的请求被取消，后续不再发起请求或重试；使用可控适配器验证调用次数和执行时序。

# Task 5: 完成客户端清理与模块独立验收

描述：后续 AI 模块任务，预计 45 分钟。将可关闭资源提供给装配层，验证多配置隔离、独立调用和失败诊断，不引入会话记忆或任务编排。

输入：完成的 AIService、mock/http 适配器、配置副本和装配层资源清理约定。

输出：AI 模块公开导出、清理入口、使用示例及边界回归用例。

依赖：Task 4；lifecycle 的逆序关闭调用约定，测试可用独立装配替身。

验收标准：
- 不创建 Workflow session 即可完成一次独立分析；AIService 不维护会话状态。由 Workflow 负责将阶段输入、输出和错误持久化并在恢复时重试失败项。
- 并发使用不同 AIConfig 时地址、模型、系统提示词和认证互不串用；调用方配置不会被执行过程修改。
- 资源清理有界且可重复，关闭失败不覆盖已有模型执行错误；取消完成后没有遗留请求任务。
- 一组离线 Mock 与本地 HTTP 测试覆盖共同结果契约、提示词、参数、总时限、取消及错误脱敏，可通过记录的命令复现。
