# Docker 部署

Docker Engine / Compose v2 或 Docker Desktop（Linux 容器）。默认部署使用后端和独立 Nginx 前端两个容器；需要单容器时使用合一镜像，它同时运行 API 和 Nginx。新方案在源码构建后生效；已发布的历史镜像和标签不会因修改仓库文件而改变。仓库、开发机和服务器的目录边界见 [项目目录结构](project-structure.md)。

## 镜像与数据的边界

| 内容 | 位置 | 更新方式 |
| --- | --- | --- |
| Python 程序、内置插件和渠道 SDK | 镜像 `/opt/workflowweave/venv` | 构建或拉取新版镜像 |
| Vue 静态文件、Nginx 配置 | 前端镜像或合一镜像 | 构建或拉取新版镜像 |
| 配置、SQLite、主密钥、日志、登录状态和 HOME | `workflowweave_state` → `/var/lib/workflowweave` | Web、CLI 或卷备份恢复 |
| 用户插件与启用设置 | `workflowweave_user_plugins` → `/var/lib/workflowweave/user-plugins` | 导入插件或维护此卷 |
| 文件引用 | 宿主 `REFERENCES_PATH` → `/var/lib/workflowweave/data/references` | 直接编辑宿主文件 |

数据卷不挂载到程序、Python 虚拟环境或内置插件目录；首次启动只创建配置，重启保留已有配置。默认 HOME 也在状态卷中，微信 SDK 的 `~/.wechatbot` 和工具缓存随卷保存。宿主依赖、密钥、数据库、状态、测试、文档和历史构建记录均不进入构建上下文。不要通过绑定宿主源码或 site-packages 修补容器；修改程序用扩展镜像，修改配置用卷或环境变量。

Python 3.12/Debian slim、运行所需 Node 24.15.0 和 CA 证书构成 `runtime`；`backend` 增加非 editable 的 Python 安装产物、轻量微信 Node SDK 和入口。`all-in-one` 在 backend 基础上加入 Nginx 和编译好的 Vue 静态文件；独立 `frontend` 仍由 Nginx/Alpine 提供静态文件。Git、uv、npm 和编译工具只用于构建，不复制到运行镜像。

```text
Python/Debian slim + Node + CA (runtime)
  └─ Python/微信安装产物 + 入口 (backend / latest)
       └─ Nginx + Vue 静态产物 (backend / full，可选合一部署)
Nginx/Alpine + Vue 静态产物 (frontend，可选拆分部署)
```

所有现有通知渠道仍包含在默认镜像中。合一镜像的 API 监听容器内 4300，Nginx 对外提供 80；拆分部署则由独立前端容器代理到 backend 服务。

## 启动与部署设置

沿用服务器 `~/.codex/example.yaml` 的代理网络、代理变量和轮转日志方式。`proxy_net` 是外部网络；这台服务器已有该网络。新服务器需先按自己的代理拓扑创建网络，且代理地址必须能从容器访问。无代理时将 `WORKFLOWWEAVE_PROXY_URL` 设为空；网络仍需存在。

在仓库根目录准备文件引用目录，Linux 上允许容器 uid 10001 写入：

```bash
mkdir -p data/references
sudo chown 10001:10001 data/references
cp .env.example .env
# 新服务器若尚无此网络：docker network create proxy_net
```

仓库已经提供空的 `data/references/.gitkeep`，所以新 clone 可以直接执行 Compose；该占位文件不会让用户引用内容进入 Git。`data-v4/` 不再使用，也不要在服务器上同时挂载第二套数据目录。

`.env` 中可以设置镜像地址、`FRONTEND_PORT`、`REFERENCES_PATH` 和 `WORKFLOWWEAVE_PROXY_URL`，无需修改 Compose。`REFERENCES_PATH` 必须已存在且允许 uid 10001 写入；Compose 不会自动创建由 root 拥有的宿主目录。应用配置仍通过 Web 保存到状态卷，bootstrap 不覆盖它。额外凭据环境变量必须明确添加到本地 `compose.override.yaml` 的 `backend.environment`，宿主环境或 `.env` 中的任意值不会自动传入容器。

使用已发布镜像：

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f backend
```

使用当前源码的新方案（尚未发布时）：

```bash
BACKEND_IMAGE=workflowweave-backend:local FRONTEND_IMAGE=workflowweave-frontend:local \
  docker compose -f compose.yaml -f compose.build.yaml up -d --build
```

前端在后端真实 `/api/health` 健康后启动。打开 `http://localhost:3000`，API 文档在 `/docs`。Web 首次启动没有来源、模型或渠道资源，请配置自己的资源。

### 单容器合一部署

合一镜像使用 `ghcr.io/striiiiiing/workflowweave-backend:full`，包含后端、前端静态文件和 Nginx。它与拆分部署共用相同的状态卷、用户插件卷和文件引用挂载：

```bash
docker compose -f compose.all-in-one.yaml pull
docker compose -f compose.all-in-one.yaml up -d
docker compose -f compose.all-in-one.yaml logs -f app
```

从源码构建合一镜像：

```bash
ALL_IN_ONE_IMAGE=workflowweave:full-local \
  docker compose -f compose.all-in-one.yaml -f compose.all-in-one.build.yaml up -d --build
```

合一部署仍通过 `FRONTEND_PORT` 对外发布，默认地址为 `http://localhost:3000`。

### 在台式机上构建并交付到服务器

在台式机仓库根目录设置本地镜像标签；只构建镜像时不需要 `proxy_net`、数据目录或服务器代理配置：

```dotenv
BACKEND_IMAGE=workflowweave-backend:local
FRONTEND_IMAGE=workflowweave-frontend:local
ALL_IN_ONE_IMAGE=workflowweave:full-local
```

构建并导出镜像：

```bash
docker compose -f compose.yaml -f compose.build.yaml build
docker image save workflowweave-backend:local workflowweave-frontend:local -o workflowweave-images.tar
```

需要交付合一镜像时单独构建并导出：

```bash
docker compose -f compose.all-in-one.yaml -f compose.all-in-one.build.yaml build
docker image save workflowweave:full-local -o workflowweave-full-image.tar
```

将归档传到服务器后导入：

```bash
docker image load -i workflowweave-images.tar
```

服务器 `.env` 使用相同的本地标签，保留服务器自己的 `WORKFLOWWEAVE_PROXY_URL`、`REFERENCES_PATH` 和 `FRONTEND_PORT`，然后执行 `docker compose up -d`。不要把台式机的代理地址复制到服务器。也可以将本地标签改成自己的镜像仓库地址，推送后让服务器拉取。

只测试后端时叠加 `compose.backend.yaml`，仅在 `127.0.0.1:4300` 发布后端。默认完整栈无需开放后端端口；合一栈只发布 Nginx 的 80。日志采用 json-file，单文件 10 MB、最多 3 个文件；应用自身日志仍在状态卷中。

## 持久化、升级与备份

来源 `path: "notes/example.txt"` 对应宿主 `data/references/notes/example.txt`（或指定的 `REFERENCES_PATH`）。文本和网页导入存到这里，实际采集重新读取文件；编辑后无需重建镜像或重启。文件必须为 UTF-8，新建不会覆盖已有路径。权限错误会明确失败。

保留旧的 `workflowweave_state`、`workflowweave_user_plugins` 和文件引用目录即可更新镜像；容器内数据路径和 uid 10001 沿用原值，升级无需自动搬迁配置、密钥和数据库。已有自定义 `plugin_dir`、`data_dir` 和主密钥设置不会被覆盖。若首次增加文件引用 bind mount，先把旧卷中的 `data/references` 内容复制到宿主目录，避免被挂载遮蔽。

```bash
docker compose stop
# 在停机期间备份下表的三项，然后再启动
docker compose start

# 常规更新
docker compose pull
docker compose up -d
```

| 备份项 | 必须保留的内容 |
| --- | --- |
| state 卷 | `config.json`、数据库/资源、`master.key`、微信登录状态、HOME 下的持久文件 |
| user_plugins 卷 | 用户插件、唯一的启用设置 `config.json` |
| REFERENCES_PATH | 全部文件引用及目录结构 |

备份时三项分别存放，恢复时分别还原到相同挂载点并保留 uid/gid 10001；不要把用户插件备份再复制进父状态卷。使用 `docker volume inspect workflowweave_state workflowweave_user_plugins` 确認实际卷名，Compose 项目名覆盖会改变卷名前缀。需要查看卷内容可用当前后端镜像执行：

```bash
docker run --rm --user 0 -v workflowweave_state:/state:ro \
  --entrypoint sh ghcr.io/striiiiiing/workflowweave-backend:latest -c 'ls -la /state'
```

`docker compose down` 保留命名卷；`down -v` 会删除状态和用户插件卷。主密钥与加密资源必须一起备份，备份目录含凭据，应保存在 Git 之外。

旧包名称升级仍需同时调整 Python import、CLI、环境变量、插件 Schema 扩展和显式保存的路径。旧 `plugins` 用户目录迁移到 `user-plugins` 的现有 bootstrap 逻辑保留；旧内置 `channel` 符号链接不复制。环境变量主密钥使用 `WORKFLOWWEAVE_MASTER_KEY`，CLI 地址使用 `WORKFLOWWEAVE_API_URL`。原主密钥内容必须保留；包含旧 Python 模块名称的执行 checkpoint 不保证跨包名恢复。

微信渠道使用 [corespeed-io/wechatbot](https://github.com/corespeed-io/wechatbot) 轻量 Node SDK，要求 Node >=22，可在 Web 扫码登录。默认状态为 `~/.wechatbot/credentials.json`，新镜像中 HOME 已持久化；也可继续使用 `/var/lib/workflowweave/wechat/main`。微信 iLink 平台每条用户消息的 context_token 最多允许回复 10 次。

## 体积依据与实测

采用 [Docker 多阶段构建](https://docs.docker.com/build/building/multi-stage/) 和 [uv 非 editable 安装](https://docs.astral.sh/uv/guides/integration/docker/#non-editable-installs)，从构建阶段只复制安装产物。数据持久化遵循 [Docker 卷语义](https://docs.docker.com/engine/storage/volumes/)；将依赖放入卷会掩盖镜像更新，因此不采用。

服务器上的 Memos、grok2api、Argus 使用独立数据/配置挂载；QwenPaw 有多处源码与 site-packages 覆盖挂载，升级时更容易与镜像不一致。历史固定版本 OpenClaw、Hermes、QwenPaw 的镜像包含更广的工具、浏览器或桌面能力，不能当成功能等价的体积基准，详见 [既有对比](../artifacts/deployment-20261008/README.md)。本方案保留本项目完整渠道能力。实测发现锁定的 sqlite-vec 0.1.9 缺少 musllinux wheel 和源码包，Alpine 后端无法安装，因此选择 Debian slim；不添加 libc 兼容层、不替换锁定依赖。

2026-10-14 在 linux/amd64、Docker 29.4.2 上实际构建并流式测量镜像，单位为十进制 MB：

| 镜像 | 压缩层内容 | 解压层 tar |
| --- | ---: | ---: |
| 默认后端 | 128.4 MB | 403.4 MB |
| 前端 | 26.5 MB | 65.4 MB |
| 默认前后端合计 | 154.9 MB | 468.7 MB |

旧 `20261007T190805Z` 后端实测解压层 652.7 MB、默认前后端合计 721.2 MB；当前分别减少约 38.2% 和 35.0%。这是与历史发布镜像的对照，两次构建的应用和锁文件快照可能不同，不能视为只改变 Dockerfile 的严格实验。合一镜像会复用后端和前端构建层。台式机可用 `docker image save` 或 `docker buildx du` 重新测量实际镜像层。

统计需分开列出压缩下载大小、解压镜像层、容器写入和业务卷；未压缩 tar 字节数不等于文件系统分配空间。不能把 runtime 和继承它的 backend 相加，也不能用 registry 压缩大小代表解压后体积。

GitHub Actions 构建并发布 `backend:latest`、`backend:runtime`、`backend:full` 和 `frontend:latest`；runtime 和 full 另有 Git SHA 标签。默认公开 GHCR 地址可在 `.env` 覆盖，已有 Docker Hub 历史镜像在 `striiiiiing/workflowweave-backend` / `striiiiiing/workflowweave-frontend`，本轮新方案未自动上传 Docker Hub。
