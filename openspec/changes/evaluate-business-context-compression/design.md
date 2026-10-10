# 业务上下文压缩评测设计

## 依据与范围

本设计依据用户 2026-10-07 两轮要求与本变更 proposal；该指令授权建立新的评测 spec。外部依据见 [references.md](references.md)。这是评测契约的结构性调整，不能在旧 Kaggle 六条件矩阵上仅替换模型名和数据集。

## 不变量与三条路线

- A 原始输入 → GPT 6.1 Sol。
- B 原始输入 → GPT 6 Luna 通用压缩 → GPT 6.1 Sol。
- C 原始输入 → GPT 6 Luna 任务定制压缩 → GPT 6.1 Sol。

使用现有上游标识 `gpt-6-luna` / `gpt-6.1-sol`；名称是用户指定的服务配置，不据此声称官方规格。压缩模型 Luna 固定 `reasoning_effort=xhigh`，下游分析模型 Sol 固定 `reasoning_effort=medium`；judge 仍固定 Luna `reasoning_effort=max`。这些值是本实验的用户指定配置，不是模型推荐参数。记录请求模型、实际响应/计费模型和可获得的快照版本，模型漂移使跨运行比较失去固定版本前提，不能静默替代。

B/C 仅允许压缩 prompt 文本及其版本/hash 不同；模型、完整输入（含相同的任务/问题信息）、预算、生成参数、分析 prompt、重试规则均相同。通用 prompt 为通用信息保留指令，定制 prompt 按任务强调证据、时间/实体关系或决议；均不访问测试参考答案。最终两份 prompt 先在开发集确定并冻结，测试集不参与调优。

每个 question_id 的 A、B、C 三条路线严格串行执行，下一条只有在上一条完成并落盘后才能开始；不同题目也默认串行，避免同一账户并发造成网关熔断、限流或难以对账。评测通过 `python -m evals.run_longmemeval` 提供项目 CLI，所有请求仍经项目 `WorkflowRunner`、`AIService`、checkpoint 和 history 归档。业务模型和 judge 通过项目渠道的 LangChain streaming/astream 路径发送，结果在服务层聚合后再写入 Workflow history。

A/B/C 使用同一数据适配层，结构化输入默认 compact JSON（避免格式化空白成为弱基线）；自然语言正文原样保留，不另跑 JSON/ZON/ISON 全排列。格式优势由独立上游证据表承担。B/C 的 Sol 输入仅含原样任务/问题、固定分析指令和压缩结果，不能通过 `$input`、历史或单任务优化把完整原文重新带入。

## 数据与指标

运行清单记录数据来源/许可、版本或内容 hash、split、样本 ID、抽样 seed、类别、模型参数、prompt hash、指标代码版本和调用顺序。LongMemEval 先对完整 500 题用固定 seed 打散；打散后的第 1–100 题保存为最终测试 holdout，任何试跑只能使用第 101 题以后。三条路线逐样本配对；先固定样本再生成，不按效果挑样本。试跑可从 holdout 之后抽 1 题或 10 题，最终测试固定使用保存的前 100 题。测试集规模、各任务输出预算和具体数据版本在数据准备任务中落盘，依据数据长度与开发集可行性确定；当前不虚构这些已完成。

- HotpotQA distractor：保留全部 distractor 文档，主指标官方答案 F1，辅报 EM。没有输出 supporting facts 时不宣称证据指标。
- MeetingBank：保持官方样本/参考摘要对齐，采用 ROUGE-L F1 为主指标并报告 ROUGE-1/2；在实现前固定官方预处理与 scorer 版本，不将词面指标解释为完整事实正确性。
- LongMemEval：主指标官方 judge 判定的正确率，同时按官方问题类型报告；沿用官方评测脚本 commit 和完整 prompt，包括拒答等分支，不替换为历史六维打分。

超出模型可用上下文、生成失败、judge 非法输出均记录显式状态；不静默截断、换模型或丢弃难例。默认单请求超时为 900 秒，可由 CLI 参数覆盖；超时只记录为失败并保留历史和账单状态。成功配对质量与总样本数、失败率一起报告，存在未评分项时标明 incomplete。

## Judge 与人工校准

用户后续明确改用 `gpt-6-luna / max` 单 judge，温度 0，官方 prompt 不变。这一决定覆盖早先双异家族 judge 的要求；报告必须标明同家族 judge 的自偏好风险，人工一致率仍待人工实际标注。

## 项目集成（用户后续要求）

业务通过本仓库 `WorkflowRunner`、`CollectorManager` CLI 来源、生产输入处理、`AIService`、Sol fan-in 和 SQLite checkpoint/业务归档执行。A 为 Sol 分析；B/C 为 Luna compress task → Sol fan-in，`order=["compress"]`、`reuse_from=None`、`single_task_optimization=false`、`analysis_failure="stop"`、`send_partial=false`。两条压缩线仅 prompt 不同，阶段预算和全部下游指令一致。

输入采用 LongMemEval S cleaned 完整历史，保留 session 时间、角色和原始正文；排除 `has_answer`、`answer_session_ids`、reference answer 和 question_type。压缩时不提供具体问题/问题日期（盲压），C prompt 只包含历史问答这一业务目标及事实/偏好、时间更新、实体数字和来源保留优先级。Sol 的三线使用同一个 system 和问题/问题日期指令。

按官方 oracle 的 500 个 question_id 固定顺序生成一次 seed=20261007 的完整洗牌映射，S 数据通过 ID 对齐，保存 original ordinal、shuffled ordinal、question_id；前 100 固定 holdout，开发区从第 101 开始。不得重新洗牌 S 数据导致 holdout 漂移。

8x 为目标输出正文 token 预算；显式使用 `o200k_base` 作统一计数基准（并非未经核实的 GPT 6 精确 tokenizer），保留实际 token 比和 AxonHub usage。压缩预算通过模型请求的 `max_tokens` 配置传递，不把 token 数字写进压缩 prompt；推理 token 与正文共用服务商输出上限，实际 finish_reason 和正文长度必须记录，不能事后剪短冒充达标。

凭据通过项目 CredentialManager 环境变量引用；HTTP hooks 仅记录脱敏请求正文、响应 ID、trace ID 和 usage，不取代生产模型调用。Judge 通过同一 AIService lease 调用固定官方消息，temperature=0；只评分成功回答。所有失败和费用缺失保留，旧 direct/oracle pilot 仅为探索，不用于项目结论。

## 成本与结论

业务费用包含 Luna 压缩+Sol 分析及失败/重试；实验总费用再加 Luna max judge。按真实 response ID 对账，不完整费用标 missing，不以 token 减少代替实际费用下降。保存每条 workflow session、配置和各阶段原始结果，分别报告 A/B/C 的质量、完整费用、压缩比及失败覆盖。

## 实施顺序

用户后续授权提示词修订：通用 B 改为用户提供的英文 CONTEXT CHECKPOINT COMPACTION 原文，直接复用项目 `AgentConfig.summary_prompt` 的默认值（`agent/context/compaction.py` 调用链的来源）；C 基于相同文本增加历史问答业务的事实/偏好、时间更新、跨会话实体、数字比较及来源优先级，并明确直接整理历史而不索要具体下游问题。仍为盲压，不输入具体问题/参考答案；token 预算仅走参数。新版固定为 `checkpoint-memory-v1`，先以第 101 题独立试跑对照旧版，再以新版累计 1→2→5→10 验证，旧 B/C 不混入新版统计。分级入口按单题的 ordinal 和提示词 hash 验证复用，避免旧 102 被误用或新 101 被重复运行。原文、C 后缀与实施任务见 [checkpoint 提示词任务](tasks/2026-10-07-checkpoint-prompts/task.md)。

先同步 spec 和集成测试；使用真实 WorkflowRunner 与受控传输验证盲压、来源脱敏、原文隔离、失败停止与落盘。测试通过后在第 101 题执行付费 smoke，再在开发区 10 题观察。最终 100 题保持保留。
