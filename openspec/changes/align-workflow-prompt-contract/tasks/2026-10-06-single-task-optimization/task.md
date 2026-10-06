# 普通汇总单任务优化修复

依据：[`design.md`](../../design.md) 与 [`specs/workflow-prompts/spec.md`](../../specs/workflow-prompts/spec.md) 中的“普通汇总单任务优化”要求；Agent 汇总例外继续依据 [`specs/workflow-agent-tasks/spec.md`](../../specs/workflow-agent-tasks/spec.md)。

- [x] 在 `FanInConfig` 和前端默认值中加入默认开启的 `single_task_optimization`。
- [x] 普通 LLM 汇总在单 Task、同 AI 配置、同模型且开关开启时复用 Task 三层消息，再追加 Task AI 回复和汇总差异。
- [x] Agent 汇总跳过优化路径，始终使用自身三层 Prompt；前端只在高级模式的普通汇总中显示开关。
- [x] 补充后端实际消息角色、关闭/不同模型回退及前端显示状态测试。

决策依据：用户本轮再次确认普通 LLM 默认开启、可在高级模式关闭，Agent 汇总不应引入 Task 差异和 AI 角色历史。现有 design 不变，本文件记录落实遗漏项；不修改历史 proposal/design。

`AIService.execute` 接受调用方构造的消息列表，保留现有重试、超时和模型校验。优化资格集中于 `ai/prompts.py::uses_single_task_optimization`，汇总消息和分析后的输入保留共用同一判断；AI 配置按 ID 与模型匹配，显式选择同一 AI/模型也符合条件。缺少成功的唯一 Task 时使用常规路径，不伪造前置 AI 消息。

默认 `true` 的依据是用户本轮要求及 design 的普通汇总默认值。缺少该字段的旧 checkpoint 在历史解码边界使用 `false`，因为原运行未启用优化、可能已释放分析输入；原始 snapshot 和 fan-in 配置从 checkpoint 原值写入 archive，避免恢复时加入新默认字段改变不可变存档摘要。新运行显式冻结开关，汇总重做继续复现原分析输入，无须重新采集。

## 验证

- `timeout 60s .venv/bin/pytest -q tests/workflow/test_summary_prompt_contract.py tests/ai/test_prompts.py tests/workflow/test_contract_archives.py`：25 项通过，29.23 秒。包含真实 AIService/AgentService、SQLite、模型可见消息、开关条件、Agent 汇总例外、旧 checkpoint 和新运行汇总重做。
- `timeout 60s .venv/bin/pytest -q tests/workflow/test_workflow_recovery.py -k 'fanin or prompts or aggregate or default_fan'`：7 项通过，34.22 秒；44 项中其余 37 项未运行。
- `timeout 60s .venv/bin/pytest -q tests/workflow/test_agent_task_integration.py tests/test_workflow_integration.py`：11 项通过，38.73 秒。
- 前端 `workflow-agent-tasks.test.ts` 7 项、`workflow-module-ui.test.ts` 7 项、`workflow-prompt-save.test.ts` 1 项通过；验证默认开启、高级模式关闭、Agent 隐藏和保存重开保留关闭状态。
- 后端变动文件 Ruff、前端 typecheck、architecture:check、生产 build、OpenSpec strict 通过。

初次前端开关测试误将 Element Plus 的 label 当作 input，修正测试选择器后通过。初次合并较大的后端回归组触及 60 秒硬超时，以上按相关范围拆分验证；不宣称全量后端通过。使用本地脚本模型，未测真实供应商缓存命中或实际计费。
