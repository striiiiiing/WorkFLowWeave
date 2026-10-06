# Docker 部署设计

用户已授权本地构建、合并与 GitHub 推送。

## 容器与依赖

多阶段 Dockerfile 提供 backend/frontend target。后端采用 Python 3.12 和 uv 0.11.2，通过 uv.lock 安装 channels extra；Node 24.15.0 满足微信官方 SDK engines，使用 package-lock.json 安装依赖。前端以相同 Node 构建 Vue，以 Nginx 提供 SPA 和 /api 代理；SSE 禁用缓存与缓冲。镜像不复制宿主虚拟环境、node_modules、配置、密钥或数据库。

后端沿用 `workflowweave start` 的单进程生命周期，以 uid 10001 运行，工作目录为可写持久卷 /var/lib/workflowweave，使 QQ SDK 默认的 botpy.log 有可写位置而无需改 SDK。Compose 默认仅在本机暴露前端 3000、后端 4300，镜像名为 workflowweave-backend:local / workflowweave-frontend:local，可通过环境变量覆盖。健康检查读取真实 /api/health，前端等待后端健康。

## 状态与插件更新

命名卷挂载 /var/lib/workflowweave。首次启动用 SystemConfig 生成容器配置：监听 0.0.0.0:4300，data_dir、plugin_dir、master_key_file 位于卷中；其它值复用现有默认值。已有配置不覆盖。

卷内 plugins/channel 是指向 /app/plugins/channel 的目录符号链接，内置插件代码随镜像更新；plugins/config.json 保存在卷内，保持现有原子替换语义。发现器已有分组目录扫描支持该链接。冲突目录显式报错。用户插件放在其它子目录。OPENCLAW_STATE_DIR 指向卷内 openclaw；凭据不进入镜像。

停机宽限为 180 秒，覆盖生命周期中多个 30 秒步骤和 10 秒资源清理；不改变应用自己的超时。down 保留卷，备份需停机后备份整个卷，包含 master.key。

## 发布与验证

本地构建两个镜像，实际启动检查健康、SPA、API、插件发现和卷恢复。Git 合并在隔离 checkout 完成，不覆盖主工作区未提交改动。正常非强制推送 GitHub。Docker Hub 需要用户自己的 namespace 和认证；上传失败不阻碍本地使用，文档给出 tag/push 和远程镜像启动命令。

## 启动验收发现的契约修正

基础开发分支已存在 SourceCall 的嵌套 discriminator：外层 kind 把 cli 映射到一个嵌套 schema 对象，而 OpenAPI 要求 discriminator.mapping 的值为引用字符串，导致 /openapi.json 返回 422。移除冗余的外层 discriminator，让 MCPCall 与按 mode 判别的 CLICall 使用普通联合；各模型的 Literal kind 和严格字段仍验证输入。保持持久化字段、CLI 运行语义和内层 mode 判别，不增加迁移。API 文档必须在真实容器中可读取，并以独立回归测试覆盖。
