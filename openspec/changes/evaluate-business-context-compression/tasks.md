# 实施任务与依据

依据：用户 2026-10-07 要求先 spec 再测试、Luna 压缩/Sol 分析、三项验证目标与 judge 约束；[proposal.md](proposal.md)、[design.md](design.md)、[spec.md](specs/business-context-evaluation/spec.md)、[来源核验](references.md)。新设计独立建 change，旧 Kaggle 任务保留为历史；本清单是本变更执行状态的唯一入口。

## 1. 规范与资料
- [x] 1.1 建立 proposal、design、能力 spec；固定模型分工、三路线和成本口径。
- [x] 1.2 使用已登录 gh 获取 ISON/ZON 固定版本结果，阅读 H2S 原文与 tsukumo 文章，注明数据冲突与证据边界。
- [x] 1.3 OpenSpec strict 验证通过；README 与本变更 Markdown 本地链接检查通过。

## 2. 先固定 spec，再写测试与实现
以下完整验收计划尚未全部完成；后续用户指定 Luna max 单 judge，覆盖 2.4、2.6、3.1–3.2 的双异家族要求。具体已验证内容见本轮状态。
- [ ] 2.1 固定数据来源/许可、split、样本 ID/seed、scorer/官方 judge commit；先全量打散 500 题并保存前 100 题作为最终 holdout，试跑只使用其后的题；在开发集确定预算与两份 prompt 后冻结。Luna 压缩固定 xhigh、Sol 分析固定 medium、judge 固定 max；压缩预算经 `max_tokens` 配置传递；100 条人工量由用户指定。
- [ ] 2.2 测试路线对照：只改 prompt 允许通过；改模型/预算/任务输入失败；参考答案泄漏、原文回流使用可辨识证据样本验证。
- [ ] 2.3 测试数据与评分：HotpotQA 已知 EM/F1、MeetingBank 已知 ROUGE 样例、LongMemEval 官方不同问题类型分支；覆盖失败、超限、缺失判定，禁止静默裁剪。
- [ ] 2.4 测试 judge：GPT/GPT 配置失败、Claude/Gemini 可通过家族校验；版本/温度/官方 prompt hash 校验；相反结论如实输出。
- [ ] 2.5 测试人工一致率：100 条中 83 条一致应为 0.83；缺失、重复 ID 与不足 100 条不能冒充完整验收。
- [ ] 2.6 测试费用：压缩+分析+双 judge+失败费用、missing 状态、judge-only 重跑不重复业务计费；少 token 但总费用更高不得标为省钱。
- [ ] 2.7 按上述失败测试修改 evals，实现 spec；保留历史账本，避免两套评分/费用真相源。
- [ ] 2.8 按顺序运行定向测试（timeout 60s）、Ruff、适用构建与最小 smoke；记录真实结果并审查 diff。CLI 默认请求超时 900 秒，三路线和题目严格串行。

## 3. 实验与报告
- [ ] 3.1 固定两位异家族 judge 的可用版本与所有运行参数，执行三路线并保存请求、输出与实际账单。
- [ ] 3.2 对完整 LongMemEval 输出做双 judge；导出盲标 100 条，待人工实际提交标签后计算两套 agreement。AI 不冒充人工标注。
- [ ] 3.3 发布按场景的质量/业务成本/实验总成本，包含无收益结果、分歧和失败；据证据更新 README。

## 本轮状态

已实现 `evals/run_longmemeval.py` 的真实 CollectorManager CLI → WorkflowRunner → AIService → Sol fan-in → SQLite 链路；新增集成测试验证盲压、日期与正文保留、标签排除、原文隔离、失败停止和归档。尚不能宣布三项业务目标成立。未发现 RecallLoom sidecar，沿用仓库 OpenSpec 任务记录，不初始化额外记忆系统。

### 2026-10-07 tokenizer 修正与 smoke

- 用户明确禁止字符估算。删除 `--allow-char-estimate`、`len(text)//4` 和 tokenizer 异常 fallback；初始化 tokenizer 失败即抛错，在读取数据和发付费请求前停止。官方 `o200k_base.tiktoken` 完整下载 3,613,922 字节，SHA256 为 `446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d`；本地和远端均验证一致。采用 design 已指定的 o200k_base 统一计数基准，不声称它是服务商 GPT 6 的专有 tokenizer；实际计费仍只用 AxonHub usage。
- 缓存目录 `/tmp/logagent-o200k-cache`，缓存键为 URL 的 SHA1 `fb374d419588a4632f3f557e76b4b70aebbca790`；运行显式设置 `TIKTOKEN_CACHE_DIR`。运行清单记录 tiktoken 版本、编码 URL/hash；后续划分记录同时保存 original ordinal 和 shuffled ordinal。
- 估算批次 `result-project-101-run2` 进程核验已退出，远端新增 `validity.json` 标 invalid，不用于质量/成本结论。没有删除历史证据。
- 实算第 101 题 `3fe836c9`（S cleaned 完整历史）为 113,979 正文 tokens，8x 预算 14,247。真实 A/B/C smoke 三请求均失败：AxonHub circuit breaker，Luna 上游出现 EOF/502。B/C 没有 Sol 请求，三线没有 judge 请求；不扩大到 10 题。最终前 100 holdout 未执行。
- 结果与 SQLite 保存于 `evals/results/20261007-project-tokenizer-smoke-101/`。AxonHub 查询的候选请求 IDs 205924/205926/205931 没有 usage，费用均 missing，不能报零；网关失败记录没有保存正文/trace 映射，时间与模型关联仍属候选匹配，不能作为完整 ID 对账。
- 验证：`timeout 60s` 下 22 项定向测试通过（17.46s），包含 tokenizer 失败不能 fallback/发请求；Ruff 两个变更文件通过。没有改动生产服务或用户其他 dirty 文件。
- 后续：网关恢复后重新用独立目录跑第 101 题；先完成压缩比、finish_reason、官方 prompt commit/hash 与真实账单匹配核验，再扩大开发区 10 题。

### 2026-10-07 reasoning 与压缩预算修订

- 用户明确要求：压缩模型 Luna 使用 `reasoning_effort=xhigh`，Sol 分析使用 `reasoning_effort=medium`；Luna judge 的 `max` 保持不变。
- 压缩 prompt 不再写 `Compress the history to at most ...`；8x 预算只通过 AI 模型配置的 `max_tokens` 请求参数传递。后续请求必须同时保存配置值、实际 usage 和 finish_reason，不能把 max_tokens 误当成正文 token 数。
- 102–110 旧配置进程在本修订前已启动，不能与新配置结果合并；停止后从新输出目录重新运行。

### 2026-10-07 串行 CLI 与超时修订

- 用户要求所有评测通过项目 CLI、复用项目 Workflow history，并禁止同题并发；实现保持 `python -m evals.run_longmemeval` 入口，A/B/C 和题目循环均为串行，完成后写入 result/history/reports。
- 用户进一步要求改为流式；业务和 judge 已通过项目 AIService 的 LangChain `streaming/astream` 聚合路径，集成测试使用 SSE Mock 验证，不改变项目 Workflow/SQLite 归档边界。
- 流式传输修正：`streaming` 为项目控制参数，渠道从 extra_body 移除该字段；LangChain 实际发送 `stream=true` 和 `stream_options.include_usage=true`。响应记录器逐块旁观 SSE，不预读完整响应；`[DONE]` 被 SDK 消费后关闭迭代器是正常行为，完成状态必须在 yield 前记录。添加渐进消费、usage、截断流和 SDK 提前关闭测试。
- 定向验证：12 项流式/lease/Workflow 测试通过（8.43s），Ruff 通过。全 AI 测试包含外部 mock/live 环境，11 项失败表现为 mock 期望内容不匹配以及 max 参数遭外部模型拒绝，不能作为本次传输验收通过；不修改这些外部环境来掩盖失败。
- 后续联调/传输烟测按用户要求只使用 Luna；正式 A/B/C 下游 Sol 配置不因联调替换。开发 10 题暂不启动。
- 流式第 102 题已完成，8 个请求全部 `stream=true`、api_key_id=11；实际请求分别为压缩 xhigh、Sol medium、judge max/temperature=0，时间戳验证所有阶段严格串行。A/B/C 均答 $65，judge 均判正确，Workflow SQLite/history 已归档。
- 单题业务成本：A $0.226414；B $0.0143293；C $0.00753444。judge 合计 $0.0001404，实验总成本 $0.24841814。C 压缩命中 112,384 cached input tokens，C 更低实际费用包含缓存收益，不能归因于定制 prompt 单独更省钱。
- 该批原 requests.jsonl 的 failed 标记来自已修复的 SDK 关闭流时记录器 bug，保留原记录并附 recording-note.json；8 条 response ID 与 AxonHub completed/usage 精确匹配，业务与 judge 结果均成功。最终定向测试 29 passed / 9.36s，Ruff 和 diff whitespace 检查通过。
- 默认单模型与 judge 超时从 300 秒提高为 900 秒，可通过 `--request-timeout` 覆盖；超时仍显式失败，不发送并发重试。
- 已停止修订前启动的 102–110 xhigh 批次；下一步只用 ordinal 102 单题验证新参数。
