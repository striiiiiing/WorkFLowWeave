# FastAPI Application Boundary

## ADDED Requirements

### Requirement: FastAPI owns application orchestration
FastAPI 应用 MUST 直接拥有应用资源装配、依赖暴露、异常映射和进程级启动/关闭编排；同一进程 MUST NOT 同时存在另一套独立组合根来启动相同资源。

#### Scenario: startup failure cleans up started resources
- **WHEN** 某个资源在应用启动序列中失败
- **THEN** 已成功创建的资源按既定关闭顺序释放
- **AND** 原始启动错误向应用启动过程报告

#### Scenario: shutdown is driven by application lifespan
- **WHEN** FastAPI lifespan 退出
- **THEN** lifecycle 按既有顺序关闭服务和订阅
- **AND** 路由层不再自行创建或销毁同一批共享资源

### Requirement: FastAPI mechanisms carry application concerns
进程级资源 MUST 使用 lifespan，请求级资源和上下文 MUST 使用 FastAPI 依赖注入，应用范围实例 MUST 使用 `app.state`，领域异常 MUST 使用 FastAPI exception handler 映射；这些职责 MUST NOT 继续塞回一个巨型 lifecycle 对象。

#### Scenario: request dependency reads app state
- **WHEN** 路由需要访问共享服务
- **THEN** FastAPI dependency 从 `app.state` 获取该服务
- **AND** 路由不自行创建第二个实例

#### Scenario: domain error is mapped at HTTP boundary
- **WHEN** 领域服务抛出已声明的领域异常
- **THEN** FastAPI exception handler 将其映射为现有 HTTP 错误格式
- **AND** lifecycle 不吞掉该请求错误

### Requirement: domain dependencies remain constructor-injected
FastAPI 装配 MUST 通过现有服务容器和构造参数向领域模块提供依赖；本次迁移 MUST NOT 被解释为跨模块 API 门面改造。

#### Scenario: workflow receives existing services
- **WHEN** FastAPI 创建 workflow 相关服务
- **THEN** 服务通过构造注入获得其既有依赖
- **AND** 本次变更不要求 workflow 通过 `interaction/api` 获取其他模块
