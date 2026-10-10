# 外部证据与引用边界

核验日期：2026-10-07。GitHub 内容通过已登录 `gh api` 获取；外部结果均为作者报告，非本项目复现。

## H2S：问题相关摘要可能改善长上下文作答

Xia et al., **Highlight-Then-Summarize: Learning to Compress Evidence for Long-Context Understanding**, arXiv:2609.31382v1，2026-09-25。[论文原文](https://arxiv.org/html/2609.31382v1)，§3.1 Table 1。

在 DocQA-RL-1.6K 上，回答模型为 Qwen3.5-Flash，问题相关摘要由 Claude Sonnet 4.6 生成，摘要过程不读取参考答案：

| 输入 | 输入 tokens | 准确率 |
| --- | --- | --- |
| LongDoc | 15.19K | 72.6 |
| Claude Summary | 0.46K | 93.0 |
| LongDoc + Claude Summary | 15.19K + 0.46K | 96.7 |
| LongDoc + Self-Summary (S) | 15.19K + 0.14K | 69.3 |
| LongDoc + Self-Summary (L) | 15.19K + 1.04K | 85.9 |

该表支持“部分场景下，问题相关摘要可减少后继模型输入并提高表现”的实验动机。短自摘要也可能降低表现，不能推导越短越好。论文主方法使用一个自回归模型生成 evidence → summary → answer，原文始终可见，并采用训练/RL；它并非 Luna → Sol 两阶段服务的复现，也未在该表给出包括摘要生成在内的 API 总账单。本项目需实测总费用。问题相关摘要为定制 prompt 提供动机，不是“只改 prompt 必然优于通用”的既有证明。

## 长历史裁剪与摘要：文章的二手报告

[tsukumo：More context is making your AI agent worse](https://tsukumo.ch/blog/more-context-makes-ai-agents-worse)，2026-06-29。文章引用 Lodha et al., **Less Context, Better Agents: Efficient Context Engineering for Long-Horizon Tool-Using LLM Agents**, arXiv:2606.10209。

文章报告 50 个工具任务中，完整历史与保留最近五次工具调用并摘要较早历史的对照：完成率 71.0% → 91.6%，累计 tokens 1,480,996 → 553,374，用时 14.56h → 5.79h。这里是任务集合累计用量，不应把 1.48M 解读为单次上下文窗口。

文章已读取；其所引论文 HTML 本次读取发生 TLS EOF，因此上述数字明确属于二手转述，尚未独立核对原论文。该场景是长程工具 Agent，不等同于本项目固定工作流，也不是本项目实际节费账单。

## ISON：固定上游表格

commit `e129543c70fc0cde918af1710d9a29816f96338d`，文件 [benchmark/BENCHMARK_300.md](https://github.com/ISON-format/ison/blob/e129543c70fc0cde918af1710d9a29816f96338d/benchmark/BENCHMARK_300.md)。报告日期 2025-12-25，20 个数据集、300 问题，DeepSeek `deepseek-chat`，temperature 0，tokenizer `o200k_base`。答案采用确定性类型比较，不是 LLM judge。

Executive Summary 的 Key Results 原值：

| 格式 | Total Tokens | Accuracy |
| --- | --- | --- |
| ISON | 3,550 | 88.3% |
| JSON Compact | 7,339 | 89.0% |
| JSON | 12,668 | 84.7% |

上游报告相对 JSON 减少 72.0% tokens；相对 compact JSON 的准确率低 0.7 个百分点，不能宣称所有指标均胜出。

**来源内部不一致**：同文件 Per-Dataset Token Comparison 的 TOTAL 是 3,549 / 7,329 / 12,658；Per-Dataset Accuracy 的 AVERAGE 是 85.7% / 88.3% / 83.3%。因此上表只代表其摘要表原值，不视作已核对原始日志的统一结论。不采用其“3.6x cost-effective”等推算作为本项目业务费用。

## ZON：固定上游表格

commit `8afdba9d2fd932e2667d63b069de416c6ca715be`，[README.md](https://github.com/ZON-Format/ZON/blob/8afdba9d2fd932e2667d63b069de416c6ca715be/README.md)。Token Efficiency Benchmark 的 Unified Dataset、GPT-4o (`o200k`) 原值：ZON 513、compact JSON 589、formatted JSON 939 tokens。相对 compact JSON 减少约 12.9%（由原始计数 `(589−513)/589` 计算）。Large Complex Nested Dataset 对应计数为 143,661 / 188,604 / 284,132，不能与 Unified 的计数混合。

另一个 Retrieval Accuracy / Per-Model Comparison 表使用 Azure `gpt-5-nano`，报告 ZON 99.0%（306/309）、JSON 96.8%（299/309）、compact JSON 91.7%（283/309）。该准确率表的 token 计数是 692 / 1,300 / 802，与上面的 token-only 表不同。

**来源内部不一致**：文字同时写“24 questions”“100%”与上述 309 个判定/99.0%，部分汇总计数和百分比也不一致；不将这些说法拼接成一项统一实验。README 的业务动机优先引用明确命名的 token-only 表，准确率保留为需核对的上游报告。上游编码配置也不能自动代表本项目关闭 dictionary compression 后的实现结果。
