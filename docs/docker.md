# Docker 启动

需要 Docker Engine 和 Compose v2；Windows 使用 Docker Desktop 的 Linux 容器。首次构建需要能访问 Docker Hub、PyPI、GitHub 和 npm。镜像包含六个通知插件及其 SDK，微信依赖较大，首次构建可能需要数分钟。

## 从源码构建并启动

在仓库根目录执行：

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f backend
```

打开 **http://localhost:3000**；API 文档 **http://localhost:4300/docs**，也可经前端访问 `/docs`。后端默认端口 4300，前端 3000，仅监听本机。需要调整时设置 `BACKEND_PORT`、`FRONTEND_PORT`，例如 `FRONTEND_PORT=3080 docker compose up -d`。后端通过真实 `/api/health` 健康检查后前端才启动。

首次启动创建空配置和数据，不创建 Collector、模型或渠道资源；在 Web 中配置自己的模型和渠道。双向渠道在实例管理处绑定对话，Email/file 仅用于 Workflow 通知。file 的相对路径位于持久卷的 `data` 目录。插件详情见 [渠道说明](../plugins/channel/README.md)。

Web 保存的加密凭据随卷持久化。如果使用环境变量凭据引用，需要在本地 `compose.override.yaml` 的 `backend.environment` 中明确传入对应变量；宿主环境和 `.env` 里的值不会自动成为容器环境。

CLI 和 stdio MCP 在后端容器中执行，宿主机的可执行文件不会自动出现在容器内。自定义命令依赖需放入扩展镜像；用户插件可放入 `/var/lib/logagent/plugins` 的其它子目录。内置 `plugins/channel` 链接指向镜像代码，请勿替换此链接。

```bash
docker compose exec backend logagent health
docker compose exec backend logagent plugins
```

## 状态、停止与更新

命名卷 `workflowweave_state` 保存 `/var/lib/logagent`，包括 `config.json`、`data` 下的 SQLite/资源/日志、`master.key`、插件启停配置及微信登录状态。后端工作目录也在卷内，QQ SDK 默认的 `botpy.log` 写入此处。后端以 uid 10001 运行；若改成宿主 bind mount，目录需要允许该用户写入。

```bash
docker compose down
# 更新源码后重建；沿用原有卷和配置
docker compose up -d --build
```

`down` 保留卷；`down -v` 会删除所有状态。备份时先停止容器，把整个卷复制到宿主目录，然后重新启动；密钥必须与加密资源一起保留。恢复时先 `docker compose create` 创建空卷，再用相同方式把备份复制回卷，最后启动：

```bash
docker compose stop
mkdir -p backup
docker run --rm -v workflowweave_state:/state:ro -v "$(pwd)/backup:/backup" \
  --entrypoint sh workflowweave-backend:local -c 'cp -a /state/. /backup/'
docker compose start

# 恢复到空卷，保留 uid 10001 的文件所有权
docker compose create
docker run --rm --user 0 -v workflowweave_state:/state -v "$(pwd)/backup:/backup:ro" \
  --entrypoint sh workflowweave-backend:local -c 'cp -a /backup/. /state/ && chown -R 10001:10001 /state'
docker compose up -d
```

备份命令默认以容器用户运行，宿主 backup 目录需允许 uid 10001 写入；Linux 可在创建后 `sudo chown 10001:10001 backup`。备份目录包含凭据，不应提交 Git。

## 微信登录

镜像包含固定版本的官方微信 SDK 和 OpenClaw CLI，登录状态写入持久卷。执行官方安装和扫码流程：

```bash
docker compose exec -w /app/plugins/channel/wechat_openclaw backend \
  npx openclaw plugins install '@tencent-weixin/openclaw-weixin@2.4.9'
docker compose exec -w /app/plugins/channel/wechat_openclaw backend \
  npx openclaw config set plugins.entries.openclaw-weixin.enabled true
docker compose exec -w /app/plugins/channel/wechat_openclaw backend \
  npx openclaw channels login --channel openclaw-weixin
```

从 `/var/lib/logagent/openclaw/openclaw-weixin/accounts.json` 获取账户 ID，填写微信渠道的 `account_id`；`state_dir` 使用 `/var/lib/logagent/openclaw`。同一账号由一个进程接收，停止另一个 OpenClaw Gateway 的轮询。

## Docker Hub 上传与使用

本地镜像为 `workflowweave-backend:local` 和 `workflowweave-frontend:local`。Docker Hub namespace 使用自己的账户，以下示例替换 `YOUR_DOCKERHUB_NAME` 与版本号；不把登录凭据写入仓库：

```bash
docker login
docker tag workflowweave-backend:local YOUR_DOCKERHUB_NAME/workflowweave-backend:0.1.0
docker tag workflowweave-frontend:local YOUR_DOCKERHUB_NAME/workflowweave-frontend:0.1.0
docker push YOUR_DOCKERHUB_NAME/workflowweave-backend:0.1.0
docker push YOUR_DOCKERHUB_NAME/workflowweave-frontend:0.1.0
```

使用已上传镜像，在仓库根目录创建 `.env`：

```dotenv
BACKEND_IMAGE=YOUR_DOCKERHUB_NAME/workflowweave-backend:0.1.0
FRONTEND_IMAGE=YOUR_DOCKERHUB_NAME/workflowweave-frontend:0.1.0
```

```bash
docker compose pull
docker compose up -d --no-build
```

Docker Hub 暂不可用时，直接使用本地构建方式；上述上传步骤可之后完成。
