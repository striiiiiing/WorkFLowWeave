# 流式超时根因修复与恢复

依据：用户已要求修 bug、解决超时、严格串行且继续分级。新版 104-C 的明确错误为 LangChain `StreamChunkTimeoutError`：已收到 1 个 chunk 后连续 120s 无内容，早于项目总时限 900s。不是 AxonHub HTTP 拒绝。

- [x] 渠道显式 `stream_chunk_timeout=None`，移除 LangChain 隐藏的 120s 阶段计时，统一由已有 AIService/lease 外围 900s 总时限管理；不是取消总超时，不更改模型/prompt/输出预算。构造参数不发送给 API，验证环境变量也不能隐式恢复阶段超时。
- [x] 审计对 partial 输入返回明确失败清单，不能缺失下游请求时抛 KeyError；仍保留技术失败。
- [x] CLI `--reuse` 显式复用同 seed/data/hash/prompt 且已完成业务与 judge 的配对行，验证 snapshot 的模型参数、问题和原文一致。新目录只运行失败/未执行行；旧失败证据保留在来源目录，并在新 manifest 记录来源、复用请求和失败请求，原费用另计，未知费用不能视为零。禁止覆盖原归档。
- [ ] 验证后恢复 103–105，仅重跑 104-C 并新增 105；累计五题验收通过后才运行 106–110，失败仍停，正确率不决定是否扩张。

固定约束：Luna xhigh 盲压 / Sol medium / Luna max judge0 / 8x 参数预算 / 12s 间隔 / 无自动重试。先受控测试，无 Sol 联调。失败请求 response ID 未能唯一匹配账单，继续查 trace/终态；费用缺失如实标记。

验证：46 passed / 11.57s（定向四文件）；Ruff 通过。lease 测试注入 `LANGCHAIN_OPENAI_STREAM_CHUNK_TIMEOUT_S=0.001`，验证构造值仍 None 且不进入请求正文。reuse 测试验证答错但评分成功的行仍复用、失败请求留在 provenance、来源文件不变、输入漂移拒绝复用。

原 partial 批次重新审计明确返回四项 incomplete 问题，不再 KeyError。新恢复根目录 `/tmp/logagent-longmemeval-pilot/result-project-checkpoint-v1-recovery-103-105`，日志 `checkpoint-v1-recovery-103-105.cli.log`；已记录 `routes_reused count=5`，原 checkpoint/history 指向 `reuse.json` 来源目录，当前新 SQLite 只包含新执行。

原 104-C 请求网关候选 id=206638（PC langchain、Luna xhigh、创建时间相差48ms）终态 canceled，external_id NULL、无 usage；流式中记录的 response ID 与网关未完成请求 external_id 未关联。该缺失必须进入总实验费用的限制，不能以成功80请求的已知费用冒充完整消耗。
