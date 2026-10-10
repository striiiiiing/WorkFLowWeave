# Docker 启动

需要 Docker Engine 和 Compose v2；Windows 使用 Docker Desktop 的 Linux 容器。默认直接拉取 GHCR 中的已发布镜像，不需要在用户机器上安装 Python、Node 或构建依赖。镜像包含六个通知插件及其 SDK，微信使用轻量 Node 依赖（本地安装约 2.7 MB）。

## 拉取镜像并启动

在仓库根目录执行：

完整栈由两个容器组成：`backend` 只加入 Compose 内部网络，前端 Nginx 通过 `http://backend:4300` 代理 API；宿主机只发布前端 **3000** 端口。

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f backend
```

打开 **http://localhost:3000**；API 文档经前端访问 **http://localhost:3000/docs**。需要调整前端端口时设置 `FRONTEND_PORT`，例如 `FRONTEND_PORT=3080 docker compose up -d`。后端通过真实 `/api/health` 健康检查后前端才启动。

只测试后端容器时叠加后端测试覆盖文件；该模式只在本机发布 `4300`，不会改变完整栈的边界：

```bash
docker compose -f compose.yaml -f compose.backend.yaml pull backend
docker compose -f compose.yaml -f compose.backend.yaml up -d backend
curl -i http://127.0.0.1:4300/api/health
docker compose -f compose.yaml -f compose.backend.yaml down
```

首次启动创建空配置和数据，不创建来源、模型或渠道资源；在 Web 中配置自己的模型和渠道。双向渠道在实例管理处绑定对话，Email/file 仅用于 Workflow 通知。file 的相对路径位于持久卷的 `data` 目录。插件详情见 [渠道说明](../src/workflowweave/plugins/channel/README.md)。

Web 保存的加密凭据随卷持久化。如果使用环境变量凭据引用，需要在本地 `compose.override.yaml` 的 `backend.environment` 中明确传入对应变量；宿主环境和 `.env` 里的值不会自动成为容器环境。

CLI 和 stdio MCP 在后端容器中执行，宿主机的可执行文件不会自动出现在容器内。自定义命令依赖需放入扩展镜像。默认插件位于镜像包内的 `workflowweave/plugins`，用户导入插件单独保存在 `/var/lib/workflowweave/user-plugins`，由独立 `user_plugins` 卷挂载。扩展镜像可通过 `builtin_plugin_dir` 将内置插件根改为独立目录。

```bash
docker compose exec backend workflowweave health
docker compose exec backend workflowweave plugins
```

## 状态、停止与更新

### 文件引用采集

文件引用保存在数据目录的 `references/` 子目录，标准 Compose 将宿主
`./data/references/` 绑定到容器 `/var/lib/workflowweave/data/references/`。
来源中的 `path: "notes/example.txt"` 对应宿主 `data/references/notes/example.txt`。
网页导入和输入文本均保存到这里；每次实际采集重新读取文件，直接编辑后无需重建镜像、重新导入或重启。

启动前准备目录，并确保后端 uid 10001 可写。Linux 示例：

```bash
mkdir -p data/references
sudo chown 10001:10001 data/references
```

权限不足时 API 明确返回保存失败，不改用其他目录。若旧状态卷中已提前放入
`data/references/` 文件，启用此绑定前先复制到宿主同名目录，避免挂载遮蔽。
使用自定义 `data_dir` 时，把容器挂载目标改为实际 `<data_dir>/references/`。
文本需为 UTF-8；新建不覆盖已有路径，修改现有文件请直接在宿主目录操作。

### 应用状态

命名卷 `workflowweave_state` 保存 `/var/lib/workflowweave`，包括 `config.json`、`data` 下的 SQLite/资源/日志、`master.key` 和微信登录状态。独立的 `workflowweave_user_plugins` 卷保存用户插件及唯一的启用设置 `config.json`。后端工作目录也在状态卷内，QQ SDK 默认的 `botpy.log` 写入此处。后端以 uid 10001 运行；若改成宿主 bind mount，目录需要允许该用户写入。

```bash
docker compose down
# 更新镜像后拉取并重启；沿用原有卷和配置
docker compose pull
docker compose up -d
```

`down` 保留卷；`down -v` 会删除所有状态。备份时先停止容器，把状态卷和用户插件卷分别复制到宿主目录，然后重新启动；密钥、加密资源和用户插件设置必须一起保留。恢复时先 `docker compose create` 创建空卷，再分别恢复两个卷，最后启动：

```bash
docker compose stop
mkdir -p backup
docker run --rm -v workflowweave_state:/state:ro -v "$(pwd)/backup:/backup" \
  --entrypoint sh ghcr.io/striiiiiing/workflowweave-backend:latest -c 'cp -a /state/. /backup/'
docker run --rm -v workflowweave_user_plugins:/state:ro -v "$(pwd)/backup:/backup" \
  --entrypoint sh ghcr.io/striiiiiing/workflowweave-backend:latest -c 'mkdir -p /backup/user-plugins && cp -a /state/. /backup/user-plugins/'
docker compose start

# 恢复到空卷，保留 uid 10001 的文件所有权
docker compose create
docker run --rm --user 0 -v workflowweave_state:/state -v "$(pwd)/backup:/backup:ro" \
  --entrypoint sh ghcr.io/striiiiiing/workflowweave-backend:latest -c 'cp -a /backup/. /state/ && chown -R 10001:10001 /state'
docker run --rm --user 0 -v workflowweave_user_plugins:/state -v "$(pwd)/backup:/backup:ro" \
  --entrypoint sh ghcr.io/striiiiiing/workflowweave-backend:latest -c 'cp -a /backup/user-plugins/. /state/ && chown -R 10001:10001 /state'
docker compose up -d
```

备份命令默认以容器用户运行，宿主 backup 目录需允许 uid 10001 写入；Linux 可在创建后 `sudo chown 10001:10001 backup`。备份目录包含凭据，不应提交 Git。

## 从旧名称版本升级

本次更名同时更新了 Python 包、CLI、环境变量、插件 Schema 扩展和容器状态目录。升级前完成正在执行的任务并停止服务，按上文备份持久卷及原主密钥。

沿用同一个 `workflowweave_state` 卷时，bootstrap 会将旧 `/var/lib/workflowweave/plugins` 中的用户插件与启用配置迁移到独立 `workflowweave_user_plugins` 卷，并将 `plugin_dir` 更新为 `/var/lib/workflowweave/user-plugins`。旧的内置 `channel` 镜像链接不会复制；自定义 `plugin_dir` 保持原值。系统配置的 `data_dir`、`master_key_file` 应分别指向 `/var/lib/workflowweave/data` 和 `/var/lib/workflowweave/master.key`。检查渠道与 MCP 资源中显式保存的路径；微信的 `state_dir` 建议使用 `/var/lib/workflowweave/wechat/main`。保留原主密钥内容。

使用环境变量主密钥时，将部署环境和系统配置的 `master_key_env` 一并改为 `WORKFLOWWEAVE_MASTER_KEY`；CLI 地址变量改为 `WORKFLOWWEAVE_API_URL`。自定义插件需使用 `workflowweave` import 和 `x-workflowweave-*` Schema 扩展；MCP 业务计数使用 `_meta.workflowweave_count`。

历史事件与业务归档仍保留原始内容；包含旧 Python 模块类型的执行 checkpoint 不承诺跨包名恢复，升级前应完成原版本的运行。升级后重新安装项目依赖并重建镜像，再通过健康检查确认服务可用。

## 微信通知服务

微信渠道内置 [corespeed-io/wechatbot](https://github.com/corespeed-io/wechatbot) 的轻量 Node SDK（Node >=22），在 Web 资源编辑器中扫码登录。Token 和上下文保存在 `state_dir`，默认 `~/.wechatbot/credentials.json`；Docker 中建议填写 `/var/lib/workflowweave/wechat/main`，该目录随状态卷持久化。旧 OpenClaw 或 WeClawBot-API 配置需重新网页登录。

微信 iLink 平台限制：每条用户消息对应的 `context_token` 最多只能回复 10 条消息。

## 镜像地址与源码构建

### 镜像层次与磁盘占用

后端按以下顺序分层，通用工具先于项目依赖安装：

```text
Python/Debian -> Node/npm -> Git/系统依赖 -> uv/uvx  (runtime)
                                                -> Python/微信依赖 -> 应用代码  (backend)
Nginx/Alpine -> Nginx 配置 -> 前端静态文件                               (frontend)
```

`ghcr.io/striiiiiing/workflowweave-backend:runtime` 提供后端的公共运行环境，供扩展镜像复用，沿用现有后端包的公开访问权限；正常部署仍只需要 backend/frontend 两个镜像。runtime 的层已包含在 backend 中，同时拉取二者不会再保存一份相同的基础层。前端运行镜像不包含 Node、npm 或前端 node_modules；这些只在构建阶段使用。需要固定基础版本时使用 `runtime-<版本标签>` 或镜像 digest。

分层主要改善构建缓存和多个版本、扩展镜像的共享，不会直接减小单套部署。Docker 的磁盘占用可能包含压缩内容与解压镜像层，下载大小、镜像层大小、实际硬盘占用应分别统计；基础镜像、应用镜像和构建缓存也不能简单相加。状态卷会随业务使用增长。

2026-10-08 发布的 `20261007T190805Z`（UTC 标签）在 linux/amd64、Docker 29.4.0 containerd 存储下实测如下，单位为十进制 MB：

| 部分 | 压缩内容 | 解压层 | 本机 Docker 镜像占用 |
| --- | ---: | ---: | ---: |
| 后端 | 188.2 MB | 652.7 MB | 840.9 MB |
| Nginx 前端 | 26.5 MB | 68.5 MB | 95.1 MB |
| 两者合计 | 214.7 MB | 721.2 MB | 936.0 MB |

公共 runtime 的 9 层已完整包含在后端中：压缩内容 149.0 MB、解压层 437.3 MB，不额外计入合计。上述数字不包含业务状态卷、容器运行时新增文件和构建缓存；其它 Docker 存储方式的实际磁盘占用可能不同。本次前端沿用原发布产物，仅增加相同版本标签；应用源码与依赖版本没有变化。

查看本机统计：

```bash
docker image ls --tree
docker system df
```

### 镜像地址

默认镜像地址为：

仓库根目录可通过 `.env` 显式确认或覆盖镜像地址：

```dotenv
BACKEND_IMAGE=ghcr.io/striiiiiing/workflowweave-backend:latest
FRONTEND_IMAGE=ghcr.io/striiiiiing/workflowweave-frontend:latest
```

Docker Hub 也已发布相同 digest 的公开镜像，可在 `.env` 中切换：

```dotenv
BACKEND_IMAGE=striiiiiing/workflowweave-backend:latest
FRONTEND_IMAGE=striiiiiing/workflowweave-frontend:latest
```

本次固定版本为 `20261007T190805Z`；公共基础环境为 `striiiiiing/workflowweave-backend:runtime` 或 `runtime-20261007T190805Z`。三个镜像均已匿名验证，发布证据见 [本轮记录](../artifacts/deployment-20261008/dockerhub-verification.json)。云服务器还需在云安全组和主机防火墙中放行实际发布端口；容器内部健康并不能证明公网可访问。

镜像由仓库的 GitHub Actions 发布；当前两个 GHCR 包已经设为 `Public`，用户无需登录即可执行 `docker compose pull`。如重新创建包或更换镜像仓库，请在对应的 Package 设置页确认可见性：

- [workflowweave-backend Package 设置](https://github.com/users/striiiiiing/packages/container/package/workflowweave-backend)
- [workflowweave-frontend Package 设置](https://github.com/users/striiiiiing/packages/container/package/workflowweave-frontend)

需要使用其他版本或镜像仓库时，在 `.env` 覆盖 `BACKEND_IMAGE` 和 `FRONTEND_IMAGE`，然后重新执行 `docker compose pull`。

开发者需要从源码构建时，显式叠加构建覆盖文件：

```bash
docker compose -f compose.yaml -f compose.build.yaml up -d --build
```
