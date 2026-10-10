## ADDED Requirements

### Requirement: Separate claims and evidence provenance
报告 MUST 区分上游格式测试、LLM 压缩业务收益、定制 prompt 收益，引用必须包含可追溯来源和适用边界。

#### Scenario: Upstream results contain conflicting summaries
- **WHEN** 上游汇总表与明细或文字冲突
- **THEN** 报告注明采用的具体表格、固定 commit 和冲突，不将其标为本项目复现，不拼接为单一已验证结果。

### Requirement: Controlled business comparison
评测 MUST 使用 GPT 6 Luna 压缩、GPT 6.1 Sol 分析，并对同一批样本生成原始、通用压缩和任务定制压缩三条路线。

#### Scenario: Fixed reasoning configuration and prompt budget
- **WHEN** 运行 A/B/C 业务路线
- **THEN** Luna 压缩请求固定 `reasoning_effort=xhigh`，Sol 分析请求固定 `reasoning_effort=medium`；压缩目标通过请求配置的 `max_tokens` 传递，B/C 压缩 prompt 不出现具体 token 数字。

#### Scenario: Serial project CLI execution
- **WHEN** CLI 运行多个题目或三条路线
- **THEN** A、B、C 和不同题目均按顺序逐一执行并在每步保存 Workflow history；默认单模型请求超时为 900 秒，可显式覆盖，超时保留失败与账单状态，不并发重试。

#### Scenario: Project streaming transport
- **WHEN** 业务模型或 judge 发起模型请求
- **THEN** 通过项目 AIService 注入的 LangChain streaming/astream 传输发送并聚合文本，保留项目 Workflow 的 checkpoint/history；不得为评测另建直连 HTTP 成功路径。

#### Scenario: Only the compression prompt changes
- **WHEN** 比较通用与定制压缩
- **THEN** 除压缩 prompt 文本及其版本外，输入、模型版本、参数、预算和全部下游配置相同，参考答案不进入生成输入。

#### Scenario: Original context stays out of downstream compressed routes
- **WHEN** 压缩结果交给分析模型
- **THEN** 分析请求包含任务/问题与压缩结果，不能包含通过共享输入、历史或优化路径注入的完整原文。

### Requirement: Reproducible benchmark scoring
评测 MUST 固定 HotpotQA distractor、MeetingBank、LongMemEval 的数据清单、样本与指标版本，并报告各任务主指标和失败覆盖率。

#### Scenario: Input or model execution fails
- **WHEN** 输入超限或模型调用失败
- **THEN** 保留失败及其账单状态，不静默截断、替换模型或删除样本；有未完成项时报告 incomplete。

#### Scenario: Tokenizer is unavailable
- **WHEN** 指定的官方 tokenizer 下载、校验或加载失败
- **THEN** 在付费请求前明确失败，不用字符长度估算；压缩预算和实际正文压缩比必须用已下载 tokenizer 计数，实际费用采用网关 usage 与账单。

### Requirement: Official independent judges
LongMemEval MUST 按用户后续决定使用 gpt-6-luna max 单 judge，温度 0，完整沿用固定 commit 的官方 prompt 与评测分支，并披露同家族偏好风险。

#### Scenario: Project workflow evaluation
- **WHEN** 业务实验执行三条路线
- **THEN** 使用真实项目采集、分析/汇总、checkpoint 和归档，盲压不读取具体问题或证据标签，压缩失败不调用下游或 judge。

### Requirement: Human agreement evidence
报告 MUST 对固定抽取的 100 条回答提供独立人工判定，并分别报告人工与固定 judge 的简单一致率与分歧记录。

#### Scenario: Some annotations or judgments are missing
- **WHEN** 100 条回答未全部完成有效标注和判定
- **THEN** 报告未完成数量，不缩小分母或将缺失判定当作一致，不宣称人工验收完成。

### Requirement: Complete cost accounting
报告 MUST 分别列出业务成本与包含 judge 的实验总成本，计入失败/重试、压缩、分析、评测的实际费用。

#### Scenario: Usage cannot be matched
- **WHEN** response/request ID 未匹配到实际账单
- **THEN** 费用标为 missing，总费用标为不完整，不按零填充。

#### Scenario: Judge-only rerun
- **WHEN** 使用既有回答重新评分
- **THEN** 复用回答和原业务账本，只新增 judge 请求和费用，不重新调用业务模型或重复累计原费用。

### Requirement: Business claims reflect paired outcomes
报告 MUST 将更便宜且更好的结论限定于预先定义且有完整配对证据的业务场景。

#### Scenario: Fewer tokens but worse quality or higher cost
- **WHEN** 压缩 token 减少但主指标下降或业务实际费用未下降
- **THEN** 报告该取舍，不宣称该场景实现更便宜且更好。
