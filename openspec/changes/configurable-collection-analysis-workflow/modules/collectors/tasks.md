# 数据采集模块任务

## 任务元信息

| 项目 | 内容 |
| --- | --- |
| 项目名称 | LogAgent v0.1 · 数据采集 |
| 关联文档 | [proposal.md](./proposal.md)、[design.md](./design.md)、[总体设计](../../design.md) |
| 任务总数 | 4 |
| 前置模块 | configuration、archive 已验收提交 |
| 执行策略 | subagent 实施，主 agent 审查与验收；本模块测试通过并提交后进入下一模块 |
| 计划产物 | logagent/collectors/、tests/test_collectors.py、tests/test_collector_plugins.py |
| 验证命令 | `rtk proxy uv run pytest tests/test_collectors.py tests/test_collector_plugins.py -q` |

## 任务列表

### Task 1：实现轻量 Collector 与原子插件发现

描述：实现声明、schema、注册表、逐文件隔离、多来源注册与可查询诊断。

输入：本模块设计 §4–5；公共模型

输出：Collector 基类、注册表、Manager；插件测试

依赖：configuration、archive

验收标准：

- [ ] 坏导入、无效 schema、重复项不破坏有效插件
- [ ] 一文件先注册后失败不会泄露部分注册

### Task 2：实现 Setter 和 Mock/日志来源

描述：按声明执行过滤、排序、投影、分组与计数，Mock 支持确定数据，日志有界尾部读取。

输入：Task 1；本模块设计 §6、§8

输出：内置 mock/logs、Setter 助手；状态与日志测试

依赖：Task 1

验收标准：

- [ ] 原始空/过滤空/失败/超时/缺失明确区分
- [ ] 未知字段与未声明能力拒绝，计数与输出顺序正确
- [ ] 日志 UTF-8 与半行/轮转边界正确且不读整个文件

### Task 3：实现有界历史来源

描述：从存档按 Workflow、次数、时间及 UTF-8 保守预算选择完整记录。

输入：Task 1；ArchiveStore；设计 §7

输出：history Collector；历史边界测试

依赖：Task 1

验收标准：

- [ ] last_n 按 session 次数，时间为左闭右开，预算截取或报错明确
- [ ] 不重采，不伪造内容，缺失与损坏不可当空成功

### Task 4：完成采集模块验收并提交

描述：运行内置与插件全部测试并独立提交。

输入：Tasks 1–3

输出：采集模块测试与验收记录；Git commit

依赖：Tasks 1–3

验收标准：

- [ ] 指定测试命令全部通过
- [ ] 并行采集和取消不串用实例结果

## 执行顺序

```mermaid
flowchart LR
    T1[Task 1] --> T2[Task 2] --> T3[Task 3] --> T4[Task 4 验收与提交]
```

推荐顺序：前置模块验收 → Task 1 → Task 2 → Task 3 → Task 4。无依赖的测试审查可并行，集成和提交按依赖顺序执行。

## 验收记录

尚未执行测试；完成后填写真实命令、结果与提交记录。
