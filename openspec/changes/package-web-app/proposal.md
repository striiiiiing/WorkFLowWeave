## Why

当前项目的 wheel 只包含 Python 包，用户必须分别启动 API 和 Vite 开发服务器。希望为单机与小规模部署提供一个可通过 pip 安装、单命令启动、浏览器直接访问的发行渠道，同时保留现有 Docker 部署。

## What Changes

- 构建 wheel 时自动构建 Vue 前端，并将 `dist` 与 Python 包一起发布。
- FastAPI 从安装包资源托管前端静态文件，并支持 Vue Router history 路由回退。
- 增加不要求用户预先创建配置文件的 `workflowweave serve` 命令；默认数据写入用户目录，支持通过参数与环境变量覆盖监听地址和数据目录。
- 将 Vue 前端声明为项目构建输入；Node.js 仅在构建 wheel 时需要。微信渠道随主项目安装，但仅在用户实际启用时启动 Node bridge。
- 在 Node wheel 支持的 x86_64 平台，`nodejs-wheel-binaries` 随主包默认安装，用户无需指定额外安装项；ARM64 不随包提供 Node，微信渠道需使用系统 `node`。包内 Node 优先于系统 `node`。两者都不可用时只记录 warning，不阻止主服务和其他能力运行；启动微信 bridge 时再明确报告渠道不可用。
- 保留现有 `workflowweave start --config`、开发模式和 Docker 部署行为。
- 分发中，采用 Hatch 自定义构建钩子运行 npm 构建前端
- 发布到pypi

## Capabilities

### New Capabilities
- `python-package-deployment`: wheel 构建、安装后服务启动、包内静态资源与持久化数据目录。

### Modified Capabilities
- `frontend`: 支持由同一 FastAPI 服务提供 SPA 静态资源与 history 路由。

## Impact

- Hatch 构建配置与 wheel 构建钩子、CLI、FastAPI app factory。
- 前端构建产物纳入 wheel，插件包数据保持可发现。
- README 与安装/启动验收；新增打包和静态资源测试。
