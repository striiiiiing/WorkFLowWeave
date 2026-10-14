# 待完成任务

已完成资料与单题 smoke，不代表 holdout、完整双 judge 或人工标注通过。实验成本与限制见 docs/evaluation.md，评测入口与账本由 evals 维护。

依据：[提案](proposal.md)、[设计](design.md)。

- [ ] 2.1 固定数据来源/许可、split、样本 ID/seed、scorer/官方 judge commit；先全量打散 500 题并保存前 100 题作为最终 holdout，试跑只使用其后的题；在开发集确定预算与两份 prompt 后冻结。Luna 压缩固定 xhigh、Sol 分析固定 medium、judge 固定 max；压缩预算经 `max_tokens` 配置传递；100 条人工量由用户指定。
- [ ] 2.2 测试路线对照：只改 prompt 允许通过；改模型/预算/任务输入失败；参考答案泄漏、原文回流使用可辨识证据样本验证。
- [ ] 2.3 测试数据与评分：HotpotQA 已知 EM/F1、MeetingBank 已知 ROUGE 样例、LongMemEval 官方不同问题类型分支；覆盖失败、超限、缺失判定，禁止静默裁剪。
- [ ] 2.4 测试 judge：GPT/GPT 配置失败、Claude/Gemini 可通过家族校验；版本/温度/官方 prompt hash 校验；相反结论如实输出。
- [ ] 2.5 测试人工一致率：100 条中 83 条一致应为 0.83；缺失、重复 ID 与不足 100 条不能冒充完整验收。
- [ ] 2.6 测试费用：压缩+分析+双 judge+失败费用、missing 状态、judge-only 重跑不重复业务计费；少 token 但总费用更高不得标为省钱。
- [ ] 2.7 按上述失败测试修改 evals，实现 spec；保留历史账本，避免两套评分/费用真相源。
- [ ] 2.8 按顺序运行定向测试（timeout 60s）、Ruff、适用构建与最小 smoke；记录真实结果并审查 diff。CLI 默认请求超时 900 秒，三路线和题目严格串行。
- [ ] 3.1 固定两位异家族 judge 的可用版本与所有运行参数，执行三路线并保存请求、输出与实际账单。
- [ ] 3.2 对完整 LongMemEval 输出做双 judge；导出盲标 100 条，待人工实际提交标签后计算两套 agreement。AI 不冒充人工标注。
- [ ] 3.3 发布按场景的质量/业务成本/实验总成本，包含无收益结果、分歧和失败；据证据更新 README。
