# docker-deployment

## Purpose

说明容器部署所需的镜像、配置、持久化和操作文档，确保启动方式可复核且运行状态与用户数据在升级后保持正确边界。实现与验收证据见 Git 历史和本地分析稿；历史验证不能替代当前版本回归。

## Requirements

### Requirement: Container deployment
The system SHALL provide backend and frontend Docker images and a Compose deployment using persistent application state.

#### Scenario: First deployment
- **WHEN** the user runs docker compose up -d --build
- **THEN** the backend initializes an empty configuration in the state volume and the frontend exposes the application after a real backend health check
- **AND** all six notification plugins are discoverable without preset Collectors
- **AND** API documentation and its OpenAPI schema are available through the frontend proxy

#### Scenario: Image update and restart
- **WHEN** containers are recreated with the same state volume
- **THEN** configuration, SQLite data, keys and WeChat login state are retained
- **AND** bundled plugin code uses the installed image version

### Requirement: Deployment instructions
The project SHALL document local startup, data retention, backup and optional Docker Hub publishing.

#### Scenario: Docker Hub unavailable
- **WHEN** registry publishing is unavailable
- **THEN** locally built images remain usable and documented tag/push commands allow later publishing

### Requirement: 引用文件位于可外部维护的数据目录

引用文件 SHALL 位于 `<data_dir>/references/`，默认本地为 `data/references/`；Docker 标准部署 SHALL 将宿主 `./data/references/` 绑定到容器 `/var/lib/workflowweave/data/references/`，使用户能够直接导入和修改文件。系统 SHALL 不把文件写入镜像或源码目录，不复制到另一份运行时缓存。既有配置、数据库和密钥的状态卷 SHALL 保持其用途，新增挂载仅针对引用子目录。

#### Scenario: Docker 宿主机修改

- **WHEN** 用户在宿主 `data/references/notes/example.txt` 修改正文，容器中的来源引用 `notes/example.txt` 并开始新采集
- **THEN** 采集读取宿主修改后的内容，无需重建镜像、重新导入或重启容器

#### Scenario: 容器重建保留引用文件

- **WHEN** 容器重建后继续使用相同宿主目录与资源配置
- **THEN** 文件仍然存在且来源按同一相对路径读取

### Requirement: 挂载与权限错误明确可见

部署文档 SHALL 说明引用根目录、相对路径映射、宿主目录准备、容器 uid 10001 的写权限，以及自定义 `data_dir` 时对应的挂载目标。目录权限或 I/O 导致保存失败时 SHALL 明确报告，不悄悄写入另一目录。启用挂载可能遮蔽容器中已有同名目录的文件时 SHALL 提醒先转移文件。

#### Scenario: 宿主目录不可写

- **WHEN** 网页提交在线文本，但宿主目录不允许容器用户写入
- **THEN** 创建请求明确失败，来源不会被报告为已完成保存，系统不改用容器内其他位置

#### Scenario: 自定义数据目录

- **WHEN** 部署者使用自定义 `data_dir` 并按文档将宿主引用目录挂载到其 `references/` 子目录
- **THEN** 引用保存和读取仍使用配置中的数据目录，不依赖第二个应用根目录设置
