# 实施记录

## 依据与决策

- 用户 2026-10-09 明确要求首次私聊消息、精确确认「成功连接」、前端及时反馈及默认插件与用户插件分离；随后确认飞书「保持单聊，我搞错了」。
- 参考 `../../design.md`（本变更设计）、`add-notification-channel-plugins/design.md` 的唯一注册器/Manager 及平台不透明地址边界；不修改旧 proposal/design。
- 飞书官方长连接使用 WebSocket；自定义机器人 webhook 面向群聊，不能用于本需求的私聊。依据：https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot ，https://open.feishu.cn/document/server-docs/im-v1/message/create ，https://www.feishu.cn/hc/zh-CN/articles/360024984973-在群组中使用机器人 。
- 可写插件开关仍存用户 plugin_dir/config.json，避免第二份配置真源；内置路径默认相对于已安装 Python 包，避免依赖工作目录和 Docker 的可写数据目录。
- 300 秒连接等待、1 秒前端状态查询、5 秒接收停止分别依据本变更 design 的人工作业预算、现有微信前端周期和 ChannelManager._STOP_TIMEOUT；发送 timeout 不变。
- 微信新增产品约束：只有用户先发消息建立上下文后才能回复，且每个 `context_token` 最多回复 10 条，因此文档和插件元数据明确“不建议作为单向通知渠道”；这是平台能力限制，不改变现有双向对话实现。

## 工作项

- [x] 用户要求先写入 OpenSpec，明确飞书保持单聊的协议更正。
- [x] 默认插件迁移、双目录发现、配置路径、Docker 分离与契约测试。
- [x] 首次连接 Manager 状态与生命周期、API、平台地址映射与测试。
- [x] 前端单向开启期间发送第一条消息提示、实时状态、取消重试与测试。
- [x] 后端定向测试、静态检查、前端构建与 smoke。
- [x] 微信单向通知限制已写入插件元数据、渠道文档、根 README 和契约测试。
- [ ] 真实测试与结果汇总，区分等待首条消息、平台拒绝和实际成功。

## 分工

MindFS group_9f0cb168ed5b31f9 关联父会话 1791481617-cf4a8677afc7，仅保留普通模板任务草稿；内置 agents 执行，不重复发布调度。父会话负责协议决策、核心连接、集成与验收。

## 2026-10-10 提交前回归

- 依据本变更 design「内置与用户插件」第 1–2 项：默认发现包内插件，隔离自定义插件的生命周期夹具必须显式指定临时空 `builtin_plugin_dir`，不能继续假设默认目录为空，也不能让测试插件与配送插件发生 ID 冲突。仅修正 `tests/lifecycle/test_lifecycle.py` 的两处配置，不改变生产默认值或设计。
- Agent 渠道 outbox 契约新增可空 `conversation_type`，对应精确断言补齐 `None`，不删除字段、不放宽整个响应校验。
- `timeout -s KILL 60s .venv/bin/python -m pytest tests/lifecycle/test_lifecycle.py -q`：22 passed / 35.21s；渠道生命周期与首次连接定向回归：23 passed / 28.26s。
- 本次仅做分组提交及本地验证，既有真实渠道记录随代码保存，不把历史记录当作本次平台联调成功。
- 提交边界：源码、测试、规格、评测数据与验收证据纳入版本控制；根 `node_modules`、`data-*` 本地运行目录、`.remote-workflow-patch` 旧副本、`frontend/1.json` 临时响应、轮转日志及部署解包副本加入忽略。沿用已有密钥、数据库、评测运行结果和传输压缩包排除规则，不删除本地文件。
- 提交前检查修正新增 `tests/test_evaluation.py` 的导入顺序以及两份 eval 模块的多余 EOF 空行。评测定向回归 17 passed / 2.11s；变更夹具与评测文件 Ruff 通过；全体 `src tests deploy evals` 排除 I001 后通过，完整 Ruff 仍有其他测试的 22 处导入排序问题，不批量格式化无关文件。
- 前端 typecheck、architecture:check、build 通过；单元测试 292 passed / 1 failed，唯一失败为 `workflow-prompt-save.test.ts`，在原始提交 `6c3bebb` 的隔离副本也复现。Python wheel 构建及 CLI `--help` smoke 通过。后端多组定向测试通过，但全量/大分组触及 60 秒硬超时，不能声称全量通过；本次未执行真实浏览器 smoke 或外部 AI/渠道联调。
- `git diff --check` 对源码和规格通过；历史 artifacts 原始终端日志保留其尾部空格和控制字符，不为消除空白告警改写原始验收证据。
