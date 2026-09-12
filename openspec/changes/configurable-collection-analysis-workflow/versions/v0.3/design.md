# v0.3：原生执行器与效果评估

## 1. 范围与兼容目标

依据 proposal §4 的“去掉 LangGraph”和“评估效果模块”。v0.1 的 LangGraph 实现在历史提交中保留；当前版本改为原生异步执行，配置和阶段存档格式兼容，用户无需重建历史记录。

## 2. 技术选型（ADR）

待后续讨论。

## 3. 原生执行器

`logagent/workflow/runner.py` 顺序推进 collect、analyze、aggregate、notify、finish，复用 WorkflowService 的阶段方法。每个阶段检查保存的完成事实，执行完成后原子写入对应内容并更新管理记录。并发仍由全局运行限制和阶段 semaphore 控制；不引入动态循环图的额外运行能力。删除运行依赖中的 LangGraph/langchain-core，独立定义模型消息类型；根目录遗留 schemas.py 迁移为不依赖 LangChain 的兼容导出。

用 v0.1 真实格式的 snapshot/collection/analysis/final 固定测试样本验证恢复：不重采，跳过成功分支，通知阶段最终内容冻结，仅补失败目标。取消、部分失败、备份关闭/损坏/过期、并发限制和定时不重叠全部复用相同行为测试。

## 4. 评估服务

### 4.1 输入与执行

`EvaluationRequest` 指定 `session_id` 和至少一个候选；候选包含 id、workflow_id 或完整 Workflow 定义，以及可选 AI/提示词覆盖。所有候选读取同一个 collection 备份，按候选来源选择重组输入；缺少必要来源即返回明确失败。候选评估不再执行采集，不触发通知、健康或对话副作用，结果保存到独立 evaluations 目录。

`EvaluationService.run(request)` 对候选有界并发，记录每个候选的分支、汇聚文本、错误、耗时、模型 usage 和评分；单候选失败不影响其他候选。来源与模型配置均记录版本快照，确保可复现。

### 4.2 评分

支持无外部调用的规则：必须包含/禁止包含关键词、最小/最大输出长度、期望 JSON 可解析与字段、参考文本匹配。每条规则输出名称、通过状态、分数和解释，汇总时明确权重；执行失败不伪装为正常零分。

可选模型评分配置 judge_ai 与 rubric，使用固定输入、候选输出和标准请求独立 AI 服务，并要求结构化 score/reason 响应；无效或超时的评分单独记为评分失败，保留候选输出。记录评分模型与 usage，不把模型主观分数宣称为正确性证明。

### 4.3 对外接口

`POST /api/evaluations` 创建评估，`GET /api/evaluations` 和 `/{id}` 查询；CLI 提供对应 HTTP 入口。报告可导出 JSON，前端可并列比较候选。评估结果不会修改原 Workflow 定义或 session。

## 5. 验收

依赖 v0.2。检查依赖锁与应用导入无 LangGraph/langchain；固定旧格式样本通过新恢复器；正常 Workflow 回归通过。评估测试验证共享采集的对象内容一致、零采集/零通知调用、不同提示词与模型覆盖、规则评分、模型评分响应校验、并发和单候选失败、报告重读与导出。
