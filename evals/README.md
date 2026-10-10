# 成本与效果评测

## LongMemEval 项目 CLI（2026-10-07）

当前 A/B/C 开发试跑走 CollectorManager CLI → WorkflowRunner/LangGraph → AIService/LangChain 流式调用，保存 SQLite checkpoint 与 history。A 为 Sol medium 直读，B/C 为 Luna xhigh 盲压再交 Sol medium；仅压缩 prompt 不同。judge 按用户后续要求固定 Luna max、温度 0、官方 prompt。下文 Kaggle 记录是独立历史实验，参数不混用。

先按 seed=20261007 洗牌 oracle 全部 500 个 ID，再以 ID 对齐 S cleaned 完整历史；前 100 个固定留给最终测试，开发试跑使用 101–110。真实 `o200k_base` tokenizer 从官方文件下载/缓存，8x 输出预算通过模型 `max_tokens` 传递，实际压缩比另报。

提示词当前版本 `checkpoint-memory-v1`：B 直接复用 `AgentConfig.summary_prompt` 的 Codex checkpoint 文本，C 在其后附加历史问答业务保留规则，见 `longmemeval_prompts.py`。运行保存提示词正文与 SHA256；分级入口拒绝复用旧提示词的单题结果。

本轮 B 记为「任务交接压缩（与历史问答业务不匹配）」，C 记为「历史问答业务压缩」。它们检验同一 checkpoint 基础上增加业务目标与保留优先级的效果；B 的结果不代表所有通用压缩提示词。正文 token 长度可能随提示词变化，8x 是两线相同的输出上限，不能把结果解释为在相同实际压缩长度下的纯提示词效果。

单次运行凭据通过 `WORKFLOWWEAVE_INSPECTION_API_KEY` 环境变量提供；分级 CLI 在部署机只读 AxonHub 数据库读取唯一 enabled 的 `PC langchain`，不会保存密钥。复用新版已验收第 101 题，累计 1→2→5→10，新增范围为 102、103–105、106–110；若单题为新版 102，则先补 101。每级完成与账单验收后自动继续；技术失败停，答案错误不停。900 秒请求时限、12 秒请求间隔、重试 0，全部串行。

```bash
python -m evals.run_longmemeval --dataset /path/longmemeval_s_cleaned.json \
  --order-dataset /path/longmemeval_oracle.json --start 101 --end 101 \
  --base-url http://127.0.0.1:19026/v1 --output /path/new-single-run
python -m evals.run_longmemeval_staged --dataset /path/longmemeval_s_cleaned.json \
  --order-dataset /path/longmemeval_oracle.json --database /path/axonhub.db \
  --singleton /path/completed-new-101 --output /path/new-staged-run \
  --base-url http://127.0.0.1:19026/v1
python -m evals.audit_longmemeval --output /path/run --database /path/axonhub.db
python -m evals.summarize_longmemeval /path/completed-new-101 \
  /path/new-staged-run/additional-102-102 /path/new-staged-run/additional-103-105 \
  /path/new-staged-run/additional-106-110 --output /path/summary.json
```

账单按 response ID 唯一关联；业务费包括压缩与分析，judge 另列并计入总费用，缺失费用不能视为零。缓存 token 和 upstream execution/channel 均保留，不能把缓存顺序收益算成 prompt 优势。开发样本和同家族 judge 仅作探索，不能替代最终 100 题、人工一致率或异家族交叉验证。

评测比较同一输入上的 JSON、ZON、ISON 和分层摘要，费用来自 AxonHub 实际账单。judge 固定 `gpt-6-luna`、`reasoning_effort=max`。本目录复用生产 `process_input`，不另外实现一套格式处理器。

## 两类数据

**公开数据**：Kaggle [Synthetic Security Logs V1](https://www.kaggle.com/datasets/beaaaaaan/programmatically-generated-security-logs-v1)，MIT 许可。固定归档、SHA-256、选样口径和列名可逆规范化见 [dataset.json](dataset.json)。使用 `aws_cloudtrail.csv` 与 `okta_system_log.csv` 两个小样例，每例选最新 100 条错误/失败，再选最新 100 条成功或其他记录；错误在前、近期记录在后。每条记录保留原始 CSV 的全部列和值，不按字段筛选、不做 token 截断；点号列名映射为 `__` 并保存映射，保证 JSON/ZON/ISON 往返可核验。100/100 是测试采样口径，不能外推源文件故障率。

原始压缩包和固定样本随运行材料记录；该数据集是程序生成数据，不等同于生产流量。

## 对照与预算

| 条件 | 输入 | 业务调用 |
| --- | --- | --- |
| `json_full` | JSON，全量选定记录 | 强模型一次 |
| `zon_full` | ZON，全量选定记录 | 强模型一次 |
| `ison_full` | ISON，全量选定记录 | 强模型一次 |
| `json_summary` | JSON，全量选定记录 → 弱模型摘要 | 弱模型一次 + 强模型一次 |
| `zon_summary` | ZON，全量选定记录 → 弱模型摘要 | 弱模型一次 + 强模型一次 |
| `ison_summary` | ISON，全量选定记录 → 弱模型摘要 | 弱模型一次 + 强模型一次 |

本轮关闭字段长度、单条来源和总输入 token 限制；完整选定样本进入 task 上下文。字符数只用于记录输入体积，真实 prompt/completion/total token 以 AxonHub usage 为准。这样先测格式本身是否省 token，再独立评估摘要损失，不把预先筛选字段造成的收益算给格式。

弱模型为 `gpt-6-luna / low`，输出上限 2,048 tokens；强模型为 `gpt-6.1-sol / medium`，输出上限 4,096 tokens。摘要路线的强模型只接收摘要，不重新携带原始数据；workflow 的 `single_task_optimization=false`，fan-in 只按 `compress` 顺序消费摘要。实际业务调用顺序按固定种子 `20261006` 打乱，并发最多 2；手动一次，每请求 300 秒，无自动重试或模型 fallback。模型上下文上限按用户提供的 105 万 token 配置假设记录，不在此处冒充官方规格。

ZON 使用 `zon-format 1.2.3` 的表格/差分编码，关闭会丢失字典字符串末尾空格的 dictionary compression；严格往返校验仍保留。三种格式使用完全相同的选定字段和值。

## LLM judge

每个非基线条件与同样例的 `json_full` 比较，先 A/B、再交换位置 B/A；judge 不知道模型名、条件名或费用。2 个样例 × 5 个比较 × 2 个位置 = 20 次 judge；业务部分为 12 次最终分析和 6 次摘要，共 18 次调用。完整 selected_sources 与确定性 reference 一起提供给 judge，评分提示词见 [judge_prompt.md](judge_prompt.md)。

六维各 1–5 分：异常召回、事实一致性、统计口径、可追溯证据、不确定性披露、行动边界。每条件先对同样例两次位置评分取均值，再按样例平均；交换位置后胜者不一致则记录 `position_conflict`，不强行选择胜者。LLM judge 只辅助比较，不预先按输出质量筛选输入。

LLM 分数是辅助证据：没有独立人工复核，合成安全日志不等于生产报告答案，且本轮只有 2 个样例/每条件一次生成，不能据此断言统计显著的优势或长期稳定性。judge 费用独立统计。

历史 BGL 评测材料仍保留在旧报告中，但不属于本矩阵，不能与本轮结果合并。当前运行的成功/失败状态、实际模型和账单以生成目录中的 `requests.jsonl`、`costs.json`、`summary.json` 为准；失败请求保留为失败，不按零费用处理。

## 运行

在仓库根目录设置 `EVAL_BASE_URL`、`EVAL_API_KEY` 环境变量后运行；脚本不自动读取生产 `.env`，不保存密钥。

```bash
uv run python -m evals.run_eval --prepare-only
uv run python -m evals.run_eval
# 环境代理不可用且需要直连时，显式选择 --ignore-proxy-env
# 上游额度恢复后，只重新评分；原始失败批次和业务报告都保留
uv run python -m evals.run_eval --judge-only evals/results/20261006-pilot
```

输出目录显示为 `evals/results/<UTC timestamp>`，保存输入、引用事实、摘要、最终报告、两次评分及所有调用记录。原始请求响应失败或 judge JSON 不合法会保留错误并将评测标为 partial，不自动重试，也不把失败正文送给 judge。

费用按每条真实响应 ID，在 `ssh myserver` 的只读 AxonHub SQLite 中关联 requests / usage_logs；记录配置模型、实际计费模型、request ID、token、缓存 token 和 `total_cost`。无法唯一关联或没有 usage 时保留 missing，不按定价表猜费用。

```bash
uv run python -m evals.costs evals/results/实际运行目录
uv run python -m evals.report evals/results/实际运行目录
```

脚本默认数据库对应本次 myserver 部署；迁移环境时用 `--database` 指定只读 SQLite URI。汇总保留业务费、judge 费、成功/失败覆盖、配对冲突和分组质量，真实结果见 [成本与效果记录](../docs/production-demo.md)。

引用：Jieming Zhu, Shilin He, Pinjia He, Jinyang Liu, Michael R. Lyu. *Loghub: A Large Collection of System Log Datasets for AI-driven Log Analytics*. ISSRE, 2023；[LogHub](https://github.com/logpai/loghub)。
