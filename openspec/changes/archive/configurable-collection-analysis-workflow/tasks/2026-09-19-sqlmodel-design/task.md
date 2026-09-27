# SQLModel 设计、测试文档与分组提交

## 决策依据

- 用户本次明确要求将 SQLModel 要求写入 design.md，补充 test.md，并拆分提交；本次已获设计修改授权。
- 以[总设计 §1.6](../../design.md#16-定义运行与恢复)为全局 SQLModel 约束来源，[Workflow test.md](../../modules/workflow/test.md)建立设计到测试的对应关系。沿用现有模块职责及官方 checkpointer 边界。
- 本任务新增于[存储迁移任务](../2026-09-19-sqlmodel/task.md)之后，记录本次设计变更；原迁移任务保留当时设计未变及测试结果的历史事实。
- 数据库配置及默认值依据迁移前实现和已通过的存储测试，设计明确其用途；测试采用每命令 60 秒硬超时，依据仓库 Testing and Validation 规则。
- 按依赖、实现与配套测试、设计与测试文档拆成三笔 commit。实现与测试同笔提交，避免删除私有连接后留下依赖该连接的测试。只提交本系列 SQLModel 文件，保留此前其他模块的工作区改动。

## 执行清单

- [x] 总设计写入 SQLModel 范围、事务、兼容、驱动边界和验收要求。
- [x] 新增 Workflow test.md，记录用例、执行命令、历史结果及验证边界。
- [x] 复核 SQLModel 定向测试、变更文件 lint、文档链接和 diff。
- [x] 分组提交并核对每笔提交文件及剩余工作区。

## 本次验证

- 使用锁定依赖重跑 SessionStore、History、Workflow recovery：72 passed，10.38 秒，命令受 60 秒硬超时限制。
- 9 个变更 Python 文件 Ruff 检查通过；新增文档相对链接目标存在。此前 190 项测试、构建及烟测结果作为迁移阶段记录保留，本次未重新声明全套执行。

## 提交划分

- `build: add SQLModel dependency and lock versions`：pyproject.toml、uv.lock。
- `refactor(storage): migrate session persistence to SQLModel`：业务表模型、存储实现、异常处理及 6 个测试文件。
- `docs(storage): specify SQLModel design and test coverage`：总设计、Workflow test.md、README 及两份 SQLModel 任务记录。
- 首笔提交由现有 post-commit 钩子自动推送到 workflow/main；后续提交使用该钩子已有的 SKIP_WORKFLOW_PUSH=1，仅保留本地提交。
