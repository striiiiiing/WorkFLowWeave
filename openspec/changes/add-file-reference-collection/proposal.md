# 文件引用采集

## Why

用户需要把现场填写的文本或导入的文件作为采集来源，并能在外部 `data` 目录中直接修改文件。现有采集只支持 MCP/CLI，缺少文件引用、文本落盘和文件导入流程；把正文存进来源配置或复用内容缓存会使外部修改不能及时生效。

## What Changes

- 在采集来源的 CLI 之后增加「文件引用」，支持引用已有文件、从浏览器导入文件，以及通过 API 将现场输入的文本保存到指定相对路径。
- 默认显示添加文件，用户勾选「输入文本」后填写正文；两种方式都允许填写保存位置。
- 文件类型由用户显式选择，当前只支持 `text`；类型与导入/输入方式分开建模，为将来的图片、DOC、PDF 留出类型扩展位置，本次不实现其处理。
- 前端生成包含浏览器时区、精确到秒的可读时间戳和随机部分的默认文件名，用户可以修改。
- 来源只保存文件类型和相对路径，每次实际采集重新读取文件，不缓存正文，不计算或验证内容 hash，不要求修改文件后重新保存来源或重启服务。
- 文件存放在 `<data_dir>/references/`；Docker 将该子目录绑定到宿主机 `./data/references/`，便于直接维护。
- 文件正文复用现有 Workflow 输入处理与来源错误/空内容策略；历史结果和同次运行的处理重试保留现有语义。

## Capabilities

### New Capabilities

当前 `openspec/specs/` 尚无已同步规范。本变更复用活动变更已有的能力目录名，以 `ADDED Requirements` 记录此次新增行为，不复制或修改既有变更。

- `collection`：文件引用来源、显式文件类型、文本创建/文件导入 API、路径与失败行为、前端编辑流程。
- `workflow`：运行时读取文件的正文进入现有输入处理链，以及新采集与历史结果的边界。
- `docker-deployment`：引用文件位于外部数据目录，Docker 通过宿主目录直接维护。

### Modified Capabilities

无已同步主规范需要修改。与活动 [MCP/CLI 采集变更](../collect-from-mcp-and-cli/proposal.md) 和 [Docker 变更](../add-docker-deployment/proposal.md) 组合使用，保留其既有行为。

## Impact

- 后端：`models.py`、`collection/`、生命周期依赖装配、HTTP 路由与 schema、Workflow 输入提取。
- 前端：来源调用类型、来源编辑器、资源 API、来源摘要与搜索。
- 部署：`compose.yaml` 的引用文件子目录挂载，以及 Docker 使用文档。
- 配置：新增 `call.kind = "file"` 分支；已有 MCP/CLI 来源无需迁移；文件正文不进入资源配置或配置快照。
- 验证：来源模型/API/运行时读取、输入处理、前端保存流程、Docker 挂载与真实浏览器 smoke；本阶段仅编写并校验 OpenSpec。
