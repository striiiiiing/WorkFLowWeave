# 业务场景下的上下文压缩成本与效果评测

## Why

用户 2026-10-07 要求先 spec、再测试，以实际业务中更省钱且保持或提高任务表现为目标。README 中的实验意向和历史 Kaggle 六条件试跑尚不足以构成可验收契约；历史同家族 judge 不满足新口径。

## What Changes

- 区分三项证据：ISON/ZON 上游格式测试；原始输入与 LLM 压缩的业务收益；仅切换压缩 prompt 的定制收益。
- 压缩固定 GPT 6 Luna，分析固定 GPT 6.1 Sol；使用 HotpotQA distractor、MeetingBank、LongMemEval。
- 建立样本配对、下游输入隔离、官方指标、异家族双 judge、人工一致率与实际费用的验收要求。
- 引用 H2S 论文及用户提供的上下文管理文章，明确外部证据适用范围。

## Capabilities

### New Capabilities
- `business-context-evaluation`: 可追溯、受控的业务上下文压缩评测与成本质量报告。

### Modified Capabilities
无。既有工作流行为不变。

## Impact

本轮先形成 spec、设计与测试任务；后续实现涉及 `evals/`、`tests/test_evaluation.py` 及评测报告。README 链接本变更。保留历史试跑，不改写既有 proposal/design，不将新规范同步为已验收主规范。
