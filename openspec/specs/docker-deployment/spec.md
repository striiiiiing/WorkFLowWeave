# docker-deployment

## Purpose

说明容器部署所需的镜像、配置、持久化和操作文档，确保启动方式可复核且运行状态与用户数据在升级后保持正确边界。未完成的实现与验收仍由所属活动变更管理，历史验证不能替代当前版本回归。

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
