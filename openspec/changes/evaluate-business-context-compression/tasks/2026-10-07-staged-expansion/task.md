# 开发集分级扩张

依据：用户明确要求单题后扩张至累计 2、5、10 题；沿用 [design.md](../../design.md) 的固定 seed、盲压、串行 CLI、流式配置和最终 holdout 隔离。

- [ ] 先验收已完成的流式第 102 题，复用结果；新增第 101 题达到累计 2 题，然后运行 103–105 达到 5 题，最后运行 106–110 达到 10 题。保留原洗牌映射和最终前 100 题；不混入旧 low、非流式、旧预算试跑。
- [ ] 每级通过项目 CLI/WorkflowRunner 执行业务，分析模型 Sol medium、压缩 Luna xhigh、judge Luna max/0，全部串行；故障联调仅用 Luna。总时限 900 秒、请求间隔 12 秒沿用已验证配置。
- [ ] 每级在扩大前核查 Workflow 完成、history/checkpoint、请求 stream=true、正确参数与 budget、完成原因、实际正文压缩比、无题目/答案标签输入、唯一 response ID 和 PC langchain 账单；不以答对率决定是否选样或扩张。
- [ ] 将账单与缓存 token 分开保存，记录计费 upstream model/channel，判断省钱、质量和 C/B 对比时明确缓存顺序影响。既有第 102 题记录器状态误标通过附注和网关 completed 证据保留，不覆盖原请求。
- [ ] 汇总全部 10 题每线正确率、失败数、实际业务成本、judge 成本、token 比和题号；保留原始 CLI 输出与项目 SQLite/history。

停止扩张的条件是技术验收失败，不是质量低于预期；失败先修原因并记录费用，不静默换模型或重跑成功请求。

## 实现与执行证据

- 项目分级入口：`python -m evals.run_longmemeval_staged`；逐级调用原有项目 CLI，在进入下一级前运行 `evals.audit_longmemeval`，不另建业务调用实现。业务或 judge 技术失败即停止当前批次；judge 判 no 属于有效结果，不停止。
- 官方评分脚本固定 `xiaowu0162/LongMemEval@9e0b455f4ef0e2ab8f2e582289761153549043fc:src/evaluation/evaluate_qa.py`。六种 question_type × abstention 两分支的全部 12 个 prompt 与官方逐字一致；保留本地实现 SHA256。
- 已有第 102 题通过真实只读 AxonHub 账单验收；8 个 response ID 唯一匹配、PC langchain id=11、全 stream=true。原请求状态误标仍由 `recording-note.json` 解释，不覆盖原始记录。
- 审计重新计数 evidence/summary、验证压缩输入完整消息及下游仅 summary+问题，B/C 请求配置与输入仅最后压缩 prompt 不同；费用为 NULL 必须记 missing，真实零费用有效。记录 upstream execution/channel（网关内部失败后成功也如实保存）。
- 模型传输和分级测试全为受控传输或 subprocess mock，不消耗付费 Sol；分级失败停止与 NULL 费用测试均列入定向验证。
- 验证：`timeout 60s .venv/bin/pytest -q tests/test_longmemeval_staged.py tests/test_longmemeval_workflow.py tests/ai/test_model_lease.py tests/test_evaluation.py`，35 passed / 9.16s；Ruff 和 `git diff --check` 通过。单题真实账单烟测通过；汇总 CLI 用单题归档验证总费用为 $0.24841814。
- 新运行根目录：远端 `/tmp/logagent-longmemeval-pilot/result-project-staged-101-110`，先启动 `additional-101-101`。所有输出使用新目录，不覆盖旧探索证据。
