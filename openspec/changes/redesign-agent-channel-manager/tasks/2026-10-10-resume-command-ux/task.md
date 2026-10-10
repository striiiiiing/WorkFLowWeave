# `/resume` 无参会话列表交互

状态：已完成实现与针对性验证。

## 目标

修正 Agent 命令入口的基本交互：输入 `/resume` 时返回历史 Agent 会话摘要列表；只有显式提供会话 ID（例如 `/resume agent_xxx`）时才读取并返回单个会话。该行为适用于 Web command、test channel 和其他复用 `CommandDispatcher` 的渠道。

## 依据与边界

- 用户要求：`/resume` 无参数应列出历史对话，带 ID 才恢复指定会话；当前实现无参数直接抛出 `invalid_argument: 恢复会话需要 session`。
- `redesign-agent-channel-manager/design.md` §2、§7：Web、test 和外部渠道复用同一个 Agent 命令端口，响应继续使用 `{channel, session, priority, kind, result}` 信封。
- `src/workflowweave/agent/service.py` 已提供 `list_sessions()`，其结果与 `/api/agents/sessions` 共用 Agent 会话投影，不新增第二份历史存储或列表来源。
- 本次只补实现任务和测试证据，不修改 `proposal.md`、`design.md` 或前端文件；`design.md` 对带 ID 的恢复契约保持不变。

## 实施决策

1. 无参数 `/resume` 返回 `kind="sessions"`，`result` 为 Agent 会话摘要列表；带参数仍返回 `kind="session"` 和单个会话详情。
2. 文本命令 `/resume` 的当前绑定 session 不视为隐式目标；否则渠道已绑定时仍会绕过列表交互。显式 API action `resume` 搭配 `session` 字段仍可按指定 ID 查询，保持已有 Web 调用能力。
3. 列表直接调用 `AgentService.list_sessions()`，不从 Workflow `session_view` 猜测或混合历史；列表项复用既有 `SessionStore.document()` 字段。
4. 渠道文本回复对空列表和有列表使用可读的 ID/标题/状态摘要；命令响应仍保留结构化 `kind/result`，不让展示格式成为新的事实来源。
5. 命令解析同时接受常见空白分隔，避免 `/resume    <id>` 被当成带空格的无效 ID；只在恢复目标处去除多余空白，保留 `/append` 正文的额外空格，不改变普通消息和未知斜线命令的错误边界。
6. 无参 `/resume` 是查询，不作为会话切换屏障等待正在执行的轮次；带 ID 的恢复仍沿用切换屏障。目标 ID 的判断由 Agent 命令信封统一提供，分发和队列分类使用同一判断，避免两份恢复规则。

## 任务

- [x] 更新 `CommandDispatcher`，区分无参列表和显式 ID 恢复；Manager 队列复用命令信封的恢复目标与切换判断。
- [x] 更新渠道命令结果的文本投影，展示历史会话列表。
- [x] 增加命令层和真实 Web/test 渠道回归测试，覆盖空列表、多个历史会话、无参命令携带当前绑定 session、带 ID 恢复、兼容的显式 action，以及活动轮次不阻塞无参查询。
- [x] 运行针对性测试、Ruff、OpenSpec 严格校验、`git diff --check`、受影响包 wheel 构建和最小服务烟测；后端单测命令使用 60 秒硬超时。

## 验证记录

- `timeout 60s .venv/bin/python -m pytest -q tests/agent/test_commands.py`：9 passed / 19.16s，覆盖正文空格保留、无参列表、空历史、当前绑定与显式目标、空白分隔、未知 ID 和重启后查询。
- `timeout 60s .venv/bin/python -m pytest -q tests/agent/test_commands.py tests/channel/test_resume_command.py -k 'not http'`：10 passed / 21.05s。此批执行在补入正文空格保留测试前，最终命令层结果以单独 9 项为准；渠道 2 项覆盖真实入队/回复、完整 ID 与标题、绑定版本不变、重复请求不重复发送、错误目标不改绑，以及活动模型轮次仍运行时的列表查询。
- `timeout 60s .venv/bin/python -m pytest -q tests/channel/test_resume_command.py -k http`：2 passed / 22.64s，使用真实应用 lifespan 与 Manager 验证 `/api/channels/web/commands` 和 `/api/agents/commands`。
- 原有恢复/切换回归批次：4 passed / 28.09s，分别为 `test_new_and_resume_allow_other_sender_to_resume_existing_session`、`test_unbound_input_is_explicit_and_resume_can_bind_any_existing_session`、`test_manager_session_switch_keeps_prior_input_in_the_old_session` 和 `test_web_channel_uses_explicit_message_action_for_slash_prefixed_text`；命令同样带 `timeout 60s`。共 17 项不同测试通过，不重复计数。
- Ruff 对两个实现文件和两个新增测试文件通过；`openspec validate redesign-agent-channel-manager --strict --no-interactive` 通过，退出码 0。
- 初次渠道整批测试被 60 秒硬超时终止，未计为通过；修正无参恢复的切换屏障后，按上面的独立批次完成验证。
- `uv build` 的源码分发包阶段耗时较长，主动终止，未计为通过；`uv build --wheel --out-dir /tmp/workflowweave-resume-20261010-dist` 通过。检查 wheel 内 `agent/commands.py` 与 `channel/manager.py` 字节内容，均与当前源码一致。
- 最小服务烟测使用临时数据目录、真实应用 lifespan/Manager 和 HTTP 请求；创建会话后携带当前 session 输入 `/resume`，得到 `kind="sessions"` 和历史列表；随后输入 `/resume <id>`，得到 `kind="session"` 与指定 ID。两个断言通过，退出码 0。
- `git diff --check` 与新增文件的行尾空白/末尾换行检查通过。最终 diff review 确认列表复用唯一会话投影，切换规则归命令信封，不新增模型调用、历史存储、隐式目标或错误吞掉分支；既有工作区改动保留。
