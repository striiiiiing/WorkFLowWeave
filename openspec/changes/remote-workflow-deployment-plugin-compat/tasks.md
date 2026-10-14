# 待完成任务

已有远端健康、资源与插件记录；完整 Workflow/SSE、Agent-MCP 和 AxonHub 成对 token/cache 仍未验收。新服务器上的三个业务例子复验合并到此入口。

依据：[提案](proposal.md)、[设计](design.md)。

- [ ] 4.3 更新远端前端 API base 指向后端，验证 health、plugin inventory、Workflow 配置/触发、SSE snapshot/terminal、历史查询和所有十个来源能力。
- [ ] 4.4 验证 Workflow 绑定 Agent 携带精确 MCP 集合；覆盖 MCP 缺失/禁用/越权时不发送的失败路径。
- [ ] 4.5 从 AxonHub 读取同一时间窗口的 input/output/cache counters，完成缓存率和直接 JSON/紧凑 JSON 成对 token 报告；字段缺失则明确报告不可用。
- [ ] 4.6 运行远端定向测试、Ruff/构建和一次真实无副作用或测试渠道 Workflow；保存 session/请求 ID，不打印凭据，并对每个大改动 commit。
- [ ] 5.1 审查 diff：无隐式 manifest 映射、静默 fallback、凭据/运行数据同步、重复插件 owner 或第二套事件存储。
- [ ] 5.2 在本任务记录本地 merge、远端 commit、十个 source inventory、SSE/Agent-MCP 证据及 AxonHub 原始计数摘要；只有全部验收条件满足才宣布完成。
- [ ] 6.1 在用户选择的新服务器复跑新闻压缩、股票调查和 GitHub issue 三个业务例子，记录真实模型、工具、通知和费用；旧服务器记录不能代替新环境验收。
