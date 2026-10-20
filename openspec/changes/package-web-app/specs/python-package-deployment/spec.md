## Purpose

为单机和小规模部署提供通过 Python 包安装并直接启动的 WorkFLowWeave 服务，同时让已安装服务能够从同一地址提供 API 与 Vue 应用。

## ADDED Requirements

### Requirement: Wheel 包含构建后的 Web 应用

发布的 Python wheel SHALL 包含与应用版本对应的 Vue 前端生产构建产物，且安装并启动服务不要求用户安装 Node.js。

#### Scenario: 从 wheel 安装前端资源
- **WHEN** 用户安装发布的 wheel 并启动服务
- **THEN** 服务可从已安装的 Python 包资源中读取前端入口及其静态资源
- **AND** 运行服务不依赖源码仓库、前端源码目录或本地 dist 目录

#### Scenario: 缺少构建时 Node.js
- **WHEN** 构建环境既没有受支持平台的 Node.js wheel，也没有系统 Node.js
- **THEN** wheel 构建以明确错误失败并指出 Node.js 构建前置条件

### Requirement: 单服务托管 Web 应用

服务 SHALL 在 API 同源地址提供 Vue 应用静态文件，且支持 history 路由的应用内导航和深层链接。API 路由及缺失的静态资源请求 SHALL 返回其真实 API 或 404 响应，不得被 SPA 回退吞掉。

#### Scenario: 打开应用和客户端深层链接
- **WHEN** 用户请求 Web 应用根路径或有效的前端深层链接
- **THEN** 服务返回 Vue 应用入口
- **AND** 前端可在同源地址继续请求 API

#### Scenario: 请求缺失资源或 API
- **WHEN** 用户请求不存在的静态资源或 API 路径
- **THEN** 服务返回相应的 404/API 响应，而非 Vue 应用入口

### Requirement: 无配置文件启动服务

CLI SHALL 提供 `workflowweave serve` 命令，使用户无需预先创建配置文件即可启动服务。命令 SHALL 在用户数据目录保存运行配置和应用数据；监听地址和数据目录 SHALL 可通过命令选项及对应环境变量配置。现有显式配置文件启动命令 SHALL 保持兼容。

#### Scenario: 使用默认值启动
- **WHEN** 用户运行 `workflowweave serve` 且未指定配置覆盖
- **THEN** 服务使用 loopback 监听和用户专属数据目录启动
- **AND** 服务生成并使用默认运行配置

#### Scenario: 覆盖监听地址与数据目录
- **WHEN** 用户通过命令选项或环境变量指定监听地址和数据目录
- **THEN** 服务使用指定值启动并将可变运行数据写入指定数据目录

#### Scenario: 保留已有显式配置启动
- **WHEN** 用户运行既有的 `workflowweave start --config <path>`
- **THEN** 服务继续使用该配置启动，且不改写为新的默认数据目录

### Requirement: 微信渠道按需启动 Node bridge

Python 主包 SHALL 包含可发现的微信渠道实现，但启动主服务不依赖 Node.js 可执行文件。微信 bridge SHALL 只在该渠道实际启用时启动；无法解析 Node.js 可执行文件时，系统 SHALL 在微信渠道启动处明确报错并将该渠道报告为不可用，不得静默忽略启动失败。

#### Scenario: 微信渠道未启用
- **WHEN** 已安装应用且微信渠道未启用
- **THEN** 服务启动不运行 Node.js bridge
- **AND** Node.js 缺失时只记录 warning，主服务和其他能力继续运行

#### Scenario: 启用微信渠道时找不到 Node.js
- **WHEN** 微信渠道被启用但支持的 Node.js wheel 与系统 `node` 均不可用
- **THEN** 微信渠道启动失败并提供可操作的错误信息
- **AND** 失败对主服务及其他能力的影响遵循现有生命周期错误处理契约

#### Scenario: 微信渠道具备 Node.js
- **WHEN** 微信渠道启用且可解析 Node.js 可执行文件
- **THEN** 微信 bridge 使用该可执行文件启动
