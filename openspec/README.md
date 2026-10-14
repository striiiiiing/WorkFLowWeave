# 规范与变更维护

`specs/<capability>/spec.md` 保存当前版本仍有效的行为契约；`changes/` 只接收正在实施或验收的增量。当前活动变更已经完成整理，`changes/` 为空；历史提案和设计保存在 `changes/archive/`，不再作为活动入口。

归档目录只保留仍有独特价值的 `proposal.md` 与 `design.md`。任务清单、日期化执行流水、临时端口和 handoff 由 Git 历史保留；本次归档前未闭环的任务与后续抉择见被 `.gitignore` 忽略的 [`artifacts/local/openspec-pending-decisions.md`](../artifacts/local/openspec-pending-decisions.md)。该本地稿不是现行规范，也不构成业务完成声明。

本轮归档保留了 2026-10-15 的 9 个 change，以及既有历史 archive。归档时只把已确认仍有效的行为增量同步到主规范；纯内部重构、撤回方案、明确暂缓项和需要外部环境证据的事项不因文档归档自动成为当前产品保证。

已明确的后续取舍：微信旧 WeClawBot-API 方案由 corespeed/wechatbot SDK 取代；Cursor 导入归入 MCP 变更；示例的新服务器验证归入远端部署；源端 Workflow Agent 与旧资源迁移记录只作历史依据，不能将未移入当前架构的优化或迁移规则发布为现行契约。

新增独立需求按单一目标创建 change；行为变更必须有增量规范，纯内部重构可声明 `skip_specs: true`。归档前核对实现与验收证据、主规范基础和增量冲突；文档齐备不代表外部账号、远端部署或真实浏览器验收已经发生。

```bash
openspec list
openspec validate --all --strict --no-interactive
```
