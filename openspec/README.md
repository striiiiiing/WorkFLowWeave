# OpenSpec 存放约定

采用官方 `spec-driven` schema，规范与代码一起保存在本仓库。目录语义依据
[OpenSpec Concepts](https://github.com/Fission-AI/OpenSpec/blob/main/docs/concepts.md)。

```text
openspec/
├── config.yaml
├── specs/                       # 已验收并同步的能力规范
│   └── <capability>/spec.md
└── changes/
    ├── <change-id>/              # 一个有边界的活动变更
    │   ├── proposal.md          # 为什么改、改什么
    │   ├── design.md            # 如何实现、技术取舍
    │   ├── tasks.md             # CLI 识别的任务清单
    │   └── specs/
    │       └── <capability>/spec.md  # ADDED / MODIFIED / REMOVED 增量
    └── archive/
        └── YYYY-MM-DD-<change-id>/
```

`spec.md` 描述外部行为与验收场景，`design.md` 描述实现方法，`tasks.md` 记录执行与验证。
不要把模块设计直接改名为 `spec.md`，也不要同时复制到主规范和增量中。

## 现有文档迁移

[可配置采集与分析变更](changes/configurable-collection-analysis-workflow/tasks.md)
仍是活动变更：历史记录包含未完成的交互任务和待集成验收项，不能因整理目录就宣布完成或归档。
它的根 `task.md` 已迁移为 `tasks.md`，现有执行记录保留，新增根复选框用于汇总验收。

该变更的 `specs/<capability>/spec.md` 从既有设计提取行为约束，以 `ADDED Requirements`
表示首次建立的能力规范；它们不是已经验收的声明。主 `openspec/specs/` 暂不填入这些待验收内容，
待完成实现、审查和验证后由标准 archive 流程同步。

现有 `modules/`、`contracts/`、`references/` 和日期化 `tasks/` 留在原 change 内，
作为详细设计、派生契约和历史证据；保留相对链接与模块 `task.md` 文件名，不生成第二套副本。
这些辅助文件不是额外的 OpenSpec artifact，也不会被 CLI 自动计入任务进度。
根任务的验收框须由维护者结合模块证据更新，不能把“文件存在”当作实现完成。

## 后续工作

1. 独立需求使用 `openspec new change <verb-object>` 新建变更，不再塞进总变更的日期任务目录。
2. 按 `proposal.md`、能力增量、`design.md`、`tasks.md` 组织工作；已存在能力使用同一路径的增量。
   纯文档或工具整理可在该变更 `.openspec.yaml` 声明 `skip_specs: true`，不能用来跳过业务规范。
3. 设计决策变更先取得用户同意，再创建新的变更任务；设计不变的实现修正更新所属任务。
   根任务记录依据、默认值理由和真实验证结果，既有 proposal/design 不因目录整理重写。
4. 验证和审查完成后运行 `openspec archive <change-id>`，同步增量至主规范并归档完整上下文。
   `status` 的 artifact 完成仅代表文档齐备，不代表任务全部通过。

```bash
openspec list
openspec status --change configurable-collection-analysis-workflow
openspec instructions apply --change configurable-collection-analysis-workflow
openspec validate --all --strict --no-interactive
```
