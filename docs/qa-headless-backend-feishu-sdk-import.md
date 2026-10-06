# QA 缺陷：Feishu SDK 导入阻塞渠道启动

## 根因

修复前，`FeishuChannel._load_sdk` 在线程中执行 `importlib.import_module("lark_oapi")`。安装的 `lark-oapi==1.7.3` 在 `lark_oapi/__init__.py` 中执行 `from .api import *`，会遍历并导入整套生成 API；通用 `lark_oapi.client.Client` 也会导入所有 API service 并逐个构造。仅飞书渠道实际使用 IM 消息请求/回复、IM `Message` resource、WebSocket `Client` 和 `EventDispatcherHandler`，因此这条全量导入路径与渠道所需组件不匹配。

原 QA 中，`test_real_lark_websocket_client_private_lifecycle_contract` 和独立的 `import lark_oapi` 都在 60 秒硬超时内卡在导入阶段；另外 8 个渠道节点通过。测试为了取得 WebSocket Client 而直接导入 SDK 根包，触发了同一根因。

## 修复方案

- `FeishuChannel._load_sdk` 通过 `PathFinder` 定位已安装 SDK，不执行其根包 `__init__.py`。仅当 `lark_oapi` 已由其他代码导入时，才复用该模块。
- 加载期间为 API 父包建立临时 package shell，避免执行生成目录的 `__init__.py`；需要的路径从官方 `EventDispatcherHandler` 源码 AST 中提取。加载结束后移除临时根包、API 父包及加载期产生的 API 模块。
- 直接导入官方事件分发器、WebSocket Client、创建/回复消息模型和 IM `Message` resource。SDK 的通用 `Client` 会导入全部 service，因此渠道内 builder 只使用官方 `Config` 与 `Message` resource，装配当前渠道实际访问的 `client.im.v1.message` 路由。
- 保留 `sdk`、`client_factory` 和 `websocket_factory` 注入路径。SDK 缺失或选定模块导入失败仍通过现有渠道错误路径明确失败，不做静默回退。
- 生命周期合同测试改为先经 `FeishuChannel._load_sdk` 装配真实 SDK，再检查官方 WebSocket Client；连接和凭据仍是测试替身，没有生产凭据或网络请求。

该方案不需要修改安装或启动路径，也未修改 proposal/design。边界是：渠道 builder 只提供此渠道使用的 IM 消息 API；若 `lark_oapi` 在渠道启动前已被其他代码全量导入，先前的导入成本无法由渠道加载器追回。官方事件分发器自身仍会导入其生成事件 processor 依赖，但不再加载全量 OpenAPI service/model 树。

## 修复后验证

- `rtk proxy timeout 60s .venv/bin/python -m pytest tests/channel/test_feishu_plugin.py -q`：PASS，9 passed in 6.81s。
- 对真实 SDK 的默认渠道 client builder 做无网络冒烟检查：PASS，生成的 `client.im.v1.message` 是官方 `lark_oapi.api.im.v1.resource.message.Message`，请求模型来自官方生成模块。
- `ruff check`、`ruff format --check`（两个改动的 Python 文件）和 `git diff --check`：PASS。

## 剩余风险

- 未覆盖真实飞书凭据或在线 API 调用；WebSocket 生命周期使用真实 SDK Client，但网络连接由测试替身接管。
- `EventDispatcherHandler` 的上游生成实现包含所有支持事件的 processor 注册，因此其依赖图仍明显大于单个 IM 消息事件；本修复跳过的是造成 60 秒阻塞的全量 API 导出和通用客户端 service 初始化。
- 若上游调整 SDK 目录结构或事件分发器的 API processor 导入形式，选定模块导入会明确失败，需要相应更新轻量加载器。
