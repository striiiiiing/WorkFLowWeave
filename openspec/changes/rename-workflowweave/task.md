# 整项目更名任务

## 决策依据

- 用户在 2026-10-06 明确要求整个项目更名，并要求先提交许可证和四项 README 待办，再执行重命名。
- 许可证与待办已由 `2c77942` 独立提交；本任务承接该提交，保留用户对 README 的编辑。
- 展示名称遵循 README 标题 `WorkFLowWeave`；Python 包、CLI、NPM 标识和目录使用小写 `workflowweave`，环境变量使用大写 `WORKFLOWWEAVE_`，分别遵循既有 Python/NPM/环境变量命名形式。
- 依据 `pyproject.toml` 的入口与构建配置、`config/registry.py` 的动态插件加载、`schema.py` 和 `mcp/runtime.py` 的扩展键、Docker bootstrap 和 Compose 的持久卷映射同步迁移，避免多套入口或隐式别名。
- 更名为机械名称与路径替换。OpenSpec 的提案和设计正文不改变行为约束；二进制旧 checkpoint 夹具保持原始内容，用来验证历史数据读取。
- 既有外部部署需更新环境变量、插件 import、Schema 扩展和显式绝对路径；迁移步骤见 `docs/docker.md`。不读取或改写用户真实数据、凭据、环境文件和密钥。

## 实施

- [x] 先完成 MIT LICENSE、Python license 元数据、Docker LICENSE 拷贝与四项 README 待办提交。
- [x] 迁移 Python 包目录、静态/动态 import、异常名称、CLI 与环境变量。
- [x] 同步前端展示、主题存储键、NPM 元数据与锁文件、插件扩展键、MCP 计数键。
- [x] 同步 Docker 用户、状态路径、bootstrap、Compose、文档、示例、测试与 IDE 模块配置。
- [x] 校验文本旧名残留、README 相对链接、待办数量和 Git whitespace。

## 验证记录

验证使用隔离 worktree，Python 3.11.15 和 Node 24.14.0；后端测试命令均设置 60 秒硬超时。

- `uv sync --group dev --extra channels --locked`：通过。
- Python import 与 `workflowweave --help`：通过。
- `ruff check src/workflowweave`：通过；更长 import 的格式和排序通过 Ruff 修正。
- 配置/采集：139 项通过。
- 根目录契约与跨模块测试：212 项通过。
- Channel：146 项通过。
- HTTP/Lifecycle：99 项通过。
- Workflow Agent 集成、汇总提示词及进程恢复：26 项通过。
- Agent/存储原语：177 项通过，1 项失败。失败是更名前基线 `test_workflow_tasks.py` 使用未导入的 `AgentService`，由另一任务的未提交修复负责；不混入更名提交。
- 前端：209 项通过，13 个 suite 因重构基线仍引用已搬迁的 `model/events`、`model/sessionProjection`、`model/transcript`、`model/agentTask` 等路径未能加载；类型检查同样在这些未修改的旧路径失败，因此未获得构建通过的证据。本任务保留失败，不新增兼容转发文件或修改无关重构行为。
- `uv build`：wheel 与 sdist 通过；wheel 包含 MIT LICENSE，元数据包含 `License-Expression: MIT` 与 `License-File: LICENSE`。
- 真实 HTTP 健康检查、新 CLI 通过 `WORKFLOWWEAVE_API_URL` 创建来源并采集 `uname -a`：通过。
- 没有调用外部付费模型、真实平台投递或执行完整 Docker 镜像构建。
