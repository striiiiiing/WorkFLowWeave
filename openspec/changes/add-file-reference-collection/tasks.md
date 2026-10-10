# 任务与决策依据

状态：用户已于 2026-10-10 选定 design.md 并明确要求「可以了，实现吧」，确认此前记录的设计草案及默认值。实现与针对性验收已完成；Docker 实际容器读写仍因 daemon 未启动保留未完成。不修改已确认的设计。

## 依据与范围

- 用户 2026-10-10 原始需求：采集增加文件/现场文本引用；现场文本由 API 按相对路径落盘；CLI 后新增选项；默认添加文件、勾选输入文本；浏览器时区的秒级可读时间戳随机文件名；运行时读、不缓存、不验 hash；文件位于外部 data；文件类型必须选择，当前仅文本。
- 用户后续要求「先写 openspec 再进行」：本阶段只新增独立变更，既有 proposal/design 和业务代码不改。
- 规范阶段完成后，用户明确确认本变更 design.md 并授权实现；下表中的设计草案默认值由该次确认生效，保留原决策依据以便审查。
- 本变更 [proposal](proposal.md)、[design](design.md)、[采集规范](specs/collection/spec.md)、[Workflow 规范](specs/workflow/spec.md)、[Docker 规范](specs/docker-deployment/spec.md)。
- [仓库存放约定](../../README.md) 要求独立需求新建 change，根 tasks.md 记录依据与验证；既有 design 改动需用户同意。
- 既有 [MCP/CLI 采集契约](../collect-from-mcp-and-cli/specs/collection/spec.md) 和 [Workflow 输入契约](../collect-from-mcp-and-cli/specs/workflow/spec.md) 定义原始结果/处理视图分离、严格 JSON、错误策略及恢复不隐式重采。
- 代码依据：`models.py` 的 `SourceCall`/`SystemConfig`、`collection/manager.py`/`invocation.py`、`workflow/input_processing.py`、`lifecycle/service.py`、`SourceConfigEditor.vue`、`resourcesApi.ts`、`compose.yaml`、`deploy/docker/bootstrap.py` 和 `docs/docker.md`。

## 结构性判断与默认值

根因是现有来源缺少文件引用模型及创建/读取边界，涉及跨模块契约。CLI 拼接 `cat` 只能临时读取，无法满足文件类型、网页落盘和统一路径约定；采用文件来源分支和单一文件服务，不维护导入/在线文本两套采集实现。

| 决策或默认值 | 依据与理由 | 确认状态 |
| --- | --- | --- |
| 默认添加文件，输入文本默认未勾选 | 用户明确要求。 | 已有用户要求 |
| 显式选择类型，当前仅 `text` | 用户明确要求；新表单初始不选类型，提交时必填。 | 类型规则已有要求；初始未选为设计草案 |
| 每次实际采集重新读，无缓存/mtime/hash 复用 | 用户明确要求直接修改文件可生效。 | 已有用户要求 |
| `<data_dir>/references/` | `SystemConfig.data_dir` 是已有数据根；独立子目录将业务引用与数据库/密钥分开。 | 设计草案 |
| `call.kind = "file"`，必填 `file_type`/`path` | 复用 `SourceCall`；创建方式不进入运行时配置，避免重复实现。 | 设计草案 |
| UTF-8，保留空白和换行，非法编码明确失败 | 与现有 CLI 文本边界一致；不自动猜测编码或生成替换字符。 | 设计草案 |
| 秒级本地时间 + 该时刻 UTC 偏移 + 8 位随机十六进制 | 用户要求可读、浏览器时区、精确到秒和随机文件名；偏移不含冒号/斜杠，随机部分降低同秒碰撞。 | 时间/时区/随机已有要求；格式为设计草案 |
| 新建默认扩展名 `.txt`，类型不从文件名推断 | 当前仅支持文本；扩展名是建议，类型仍独立显式选择。 | 设计草案 |
| 路径冲突 HTTP 409，不覆盖、不自动改名 | 用户可直接维护外部文件，创建不应静默损坏或改变其目标。 | 设计草案 |
| 来源超时沿用 60 秒，错误/空策略沿用 notice，限额沿用继承 | 直接复用 `SourceConfig` 与前端现有默认值，不新增文件专属超时或预算。 | 设计草案，依据现有默认值 |
| 历史获取结果只服务原运行，未来采集不复用 | 既有获取/处理分离和恢复契约；用户要求运行时读取，不等于用当前文件改写历史事实。 | 设计草案，保留既有恢复边界 |
| Docker 仅绑定 `data/references` 子目录 | 现有 state 卷管理数据与密钥；新增可宿主编辑的业务文件目录，避免迁移整个状态根。 | 设计草案 |

## 任务

### 1. 规范阶段

- [x] 1.1 检查来源模型、采集调用链、前端表单、数据根与 Docker 挂载约定。
- [x] 1.2 新建 proposal、design、三份能力增量和本任务清单，明确需求与设计草案默认值的区别。
- [x] 1.3 通过本变更 OpenSpec 严格校验，复核相对链接、跨规范语义及工作区 diff；记录真实结果。

### 2. 实现阶段

- [x] 2.1 依据确认后的设计增加文件来源模型与单一文件服务，统一路径/UTF-8/独占创建/实时读取；生命周期注入，不读取正文作为配置验证。
- [x] 2.2 实现文本创建与原始字节导入 API，覆盖路径、类型、冲突、非法编码和存储错误；确保 OpenAPI 可正常生成。
- [x] 2.3 接入采集管理器与公共调用，保留明确的获取结果、错误与空内容策略，拒绝非 MCP 参数覆盖。
- [x] 2.4 文件原始正文接入既有 Workflow 输入处理；新采集读取最新内容，处理重试/历史恢复不隐式重读。
- [x] 2.5 前端增加文件引用、必选文件类型、导入/输入文本切换、相对保存位置与时区时间戳随机文件名；两个保存作用域共用流程。
- [x] 2.6 前端区分文件创建与来源保存，失败可重试且不重复创建；来源摘要和搜索支持路径。
- [x] 2.7 增加 Docker 子目录挂载与目录/权限说明，验证自定义数据目录的对应方式。

### 3. 验证阶段

- [x] 3.1 针对性后端测试：模型必填类型、API 字节/换行保持、路径越界、符号链接、冲突、失败清理、文件删除/非法编码、空文件/非空标量；单次后端单测命令硬超时 60 秒。
- [x] 3.2 集成验证：首次采集后直接改文件，再采集得到新正文；普通文本/JSON 输入处理、显式重跑与历史结果边界、MCP/CLI 无回归。
- [x] 3.3 前端测试：默认导入、类型必选、模式切换保留路径、秒级文件名与正/负/夏令时时区偏移、编辑旧引用、文件创建或来源保存失败后的重试。
- [x] 3.4 按针对性测试、类型/lint、构建、最小 smoke 顺序执行；真实浏览器验证桌面/移动布局与保存流程，不能把启动服务器当作通过。
- [ ] 3.5 验证 Compose 挂载配置与容器实际读取宿主修改，容器重启不丢失文件；不能只凭目录配置宣称通过。
- [x] 3.6 按 design/spec 审查最终 diff，排查正文缓存、hash 门禁、双重路径来源、重复实现、静默覆盖/回退和未经说明的历史恢复变化。

## 验证记录

- 2026-10-10：`openspec validate add-file-reference-collection --strict --no-interactive` 通过，退出码 0。
- `openspec status --change add-file-reference-collection` 确认 proposal/specs/design/tasks 共 4/4 planning artifacts 齐备；只表示文档齐备。
- 2026-10-10：文件相关后端批次 `timeout 60s pytest -q tests/collection/test_file_references.py tests/interaction/test_file_reference_api.py tests/workflow/test_file_reference_flow.py tests/lifecycle/test_file_reference_lifecycle.py` 通过，41 passed；此前针对性回归批次另有 78 passed，前端文件引用批次 22 passed。
- 2026-10-10：前端 `npm run typecheck`、`npm run build`、Prettier/Ruff 相关检查通过；`git diff --check` 通过。生产构建仅有既有 zod/Rollup 注释 warning。
- 2026-10-10：真实浏览器验收通过：在线文本保存 201 并采集正文 `现场正文\n第二行`；导入文本保存 201，CRLF/空行原样保留；外部直接修改 `browser/online.txt` 后再次采集读到新正文；重复创建返回 409；桌面 1440×1000 与移动 390×844 表单无文档横向溢出，证据见 [`artifacts/file-reference-smoke/browser/desktop-form.png`](../../../artifacts/file-reference-smoke/browser/desktop-form.png) 和 [`artifacts/file-reference-smoke/browser/mobile-form.png`](../../../artifacts/file-reference-smoke/browser/mobile-form.png)。
- 2026-10-10：真实生命周期重启测试 1 passed，关闭并重新启动后读取外部修改；独立 smoke 服务保持运行供手工试用。
- 2026-10-10：Docker Compose 配置已用宿主 `docker.exe compose config --format json` 解析并确认挂载目标；当前 WSL Docker daemon 未启动，未宣称容器实际读写/重启验收，3.5 保持未完成。
- 2026-10-10：扩大旧 `tests/lifecycle/test_lifecycle.py` 回归为 17 failed / 42 passed，首个失败与本变更无关（既有插件装配断言仍期待旧的仅 `web` 集合，当前生命周期包含 packaged plugins）；其余失败伴随旧夹具/线程清理问题。未修改该既有测试，避免把无关基线变化归因于文件引用。
- 本变更 6 个 Markdown 文件、11 处本地相对链接检查通过，行尾空白与末尾换行检查通过；`git diff --check` 通过。新增文件单独检查，避免未跟踪文件未进入 git diff 而遗漏。
- 跨文档复核覆盖显式文件类型、默认导入/在线输入、相对路径与 Docker 目录映射、时区文件名、实时读取、失败与冲突、同次处理/历史结果边界，以及任务默认值依据。
- 规范阶段只新增 `openspec/changes/add-file-reference-collection/` 中的文档；实现阶段按已确认设计修改业务代码并完成针对性验收。本记录不使用文档校验代替功能验收。
