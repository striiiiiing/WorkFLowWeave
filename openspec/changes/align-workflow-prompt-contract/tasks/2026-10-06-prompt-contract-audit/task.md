# Prompt 契约核验与修正

## 依据与范围

用户于本轮确认：分析和常规模型汇总使用 `[System, Human(input), Human(差异)]`；Task 的 system/input 独立覆盖优先，否则继承 Workflow；Human 输入模板与差异必填。普通同配置、同模型的单 Task 汇总默认开启优化，高级模式可关闭；Agent 汇总始终使用常规三层并隐藏优化按钮。随后用户明确授权空 `order` 默认加入 `$input`，因此普通与 Agent 汇总统一采用 `$input` 加 Task 声明顺序，显式非空 `order` 覆盖默认。

根因：迁入实现只对 Agent 校验必填，普通任务沿用早期可空契约；Agent 与普通汇总默认输入顺序分叉。属于共享模型/API 契约修正，统一新配置入口校验，通用消息构造器仍支持历史两层请求及 Agent 内部输入注入。LLM、Agent 和优化路径通过同一个 `resolve_prompts` 解析优先级，避免重复业务规则。纯文本拼接不调用模型，沿用 design 无需差异指令的约定。

用户已授权修改不符合的旧 Change。依据本 Change proposal/design/spec 更新设计文字并新增本任务记录，不重写历史验收。早期 layer-workflow-prompts 的可空模板/差异要求由本 Change 覆盖。`single_task_optimization=true` 依据用户要求保持；旧 checkpoint 缺少字段仍使用 false，不改变冻结行为。历史快照的宽松解码仅在持久化恢复上下文有效，不暴露给 API。

## 实施

- [x] 对普通与 Agent 新配置统一校验非空差异、非空输入模板；保留空 System 作为显式覆盖。
- [x] 空 order 的前后端默认统一为 `$input` 加 Task 顺序；显式 order 可以省略 `$input`。
- [x] 保留普通汇总五条优化消息、默认开启/高级可关闭，以及 Agent 三层与隐藏优化选项。
- [x] 修复旧资源迁移保留手工 Prompt、提取差异、缺少差异明确要求补齐；旧运行快照保持原模板含义。
- [x] 旧 Agent 创建事件显式解码原系统/输入模板；旧差异为空的历史 Task 使用原固定首轮文本保留请求摘要，后续对话与原 Workflow 冻结结果保持独立。
- [x] 验证模型实际消息、校验/API、历史兼容、前端保存重开及 OpenSpec 严格检查。

不涉及采集/分析/汇总阶段数量或空运行结果策略的改造。

## 验证结果

- 最终 Prompt 消息、汇总优化/默认 order、继承覆盖和新配置必填组：38 项通过（26.00 秒），实际调用真实 AIService/AgentService/WorkflowRunner 与 SQLite，模型传输用本地 ScriptedModel。覆盖普通和 Agent 空 order 默认加入 `$input`、显式 order 省略及三层/五层角色顺序。
- Agent 执行、幂等与恢复组：38 项通过（41.66 秒）；新增旧 Agent 创建事件/原首轮请求恢复：1 项通过（28.81 秒），不重复已完成模型轮次。
- Prompt 迁移：4 项通过（3.14 秒）；资源原子发布/引用/迁移回归：25 项通过（26.53 秒）；Workflow 汇总顺序/层级覆盖回归：6 项通过（29.93 秒）。这些分组不累计为全量测试。
- 前端 Agent/必填/空 order/优化 UI：11 项通过；既有 Workflow UI：7 项通过；空输入模板保存拦截、修正后保存和重开：1 项通过。
- Vue TypeScript 类型检查、生产构建（3776 模块）、所有变动 Python 文件 Ruff、变动前端文件 Prettier、git diff --check 通过；三个相关 Change 的 OpenSpec strict 校验通过。

所有后端测试进程使用 `timeout 60s`。初次整组遇到启动/文件读取耗时达到硬上限，拆分后完成以上验证；不宣称全量后端通过。首轮新增前端测试误把 ElMessage 提示当作页面正文，改为断言实际提示调用和 API 保存拦截，没有修改产品行为来迎合测试。测试中已有空 Prompt 的有效配置 fixture 已显式填写指令；产品不会生成默认差异，也不放宽新 API 必填要求。尝试按用户指定模型委派测试，但子代理未能读取任务正文，因此上述最终验证由主代理实际运行。
