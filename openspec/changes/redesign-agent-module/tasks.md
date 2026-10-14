# 待完成任务

静态图、共享存储原语和职责迁移已实施，历史定向验证通过；跨边界矩阵、完整构建/应用 smoke 与最终所有权审查仍待闭环。

依据：[提案](proposal.md)、[设计](design.md)。

- [ ] 5.1 按目标目录迁移既有测试，执行 A1–A11 及 storage_primitives、LangGraph runtime、LangChain Vue adapter 的跨边界场景；每次后端单测命令设置 60 秒硬超时，记录结果，失败不得静默跳过。
- [ ] 5.2 运行静态依赖/lint、受影响 Python 包构建、前端 typecheck/build 和最小真实应用 smoke；验证会话发送、工具结果、停止、SSE 重连、前端卸载与重启后查询。
- [ ] 5.3 核对 design §7 所有旧职责已迁移、无重复任务/存储/默认工具来源/前端 stream 状态；用 diff review 和导入扫描验证，保留用户已有改动。
- [ ] 5.4 运行 OpenSpec 严格校验，核对所有实现任务的测试证据；仅全部验收后归档本 change，保持 skip_specs，不替其他活动 change 同步业务规范。
