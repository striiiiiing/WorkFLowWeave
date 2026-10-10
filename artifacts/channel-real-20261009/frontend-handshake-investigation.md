# QQ、飞书、Telegram 前端首次连接调查

调查范围：仅检查前端渠道编辑/开启流程、现有 API 封装及测试；没有修改产品代码，也没有读取或记录平台凭据。

## 现状

- [ChannelEditor.vue](../../frontend/src/modules/resources/ui/ChannelEditor.vue#L98) 的“启用渠道”开关只改本地草稿。保存按钮随后调用 [useChannelEditor.ts](../../frontend/src/modules/resources/composables/useChannelEditor.ts#L53) 的 create/replace；成功时只提示“资源已保存”。前端没有等待首条消息、连接状态或“成功连接”反馈。
- `agent_enabled` 只控制“接入 Agent 对话”，且仅在能力声明包含 `conversation` 时出现。QQ、飞书、Telegram 当前都声明 `notification` 与 `conversation`，所以它区分通知单向模式与 Agent 双向模式，但不负责通知渠道的首次连接。
- 新建渠道默认 `enabled: true`，见 [defaults.ts](../../frontend/src/modules/resources/model/channel/defaults.ts#L3)。因此不能只依赖开关的 false→true 变化识别首次开启；应由明确的保存并开启动作或显式启用动作触发握手。
- [ChannelList.vue](../../frontend/src/modules/resources/ui/ChannelList.vue#L12) 只展示实例编号、能力名、编辑和删除，没有启用开关或运行状态。资源页在编辑器保存后关闭弹窗并刷新列表，见 [ResourcesPage.vue](../../frontend/src/pages/resources/ResourcesPage.vue#L311)。
- [resourcesApi.ts](../../frontend/src/modules/resources/api/resourcesApi.ts#L14) 有保存、对话绑定，以及专供扫码登录的 start/status/verify/cancel API。登录状态模型包含 `waiting/scanned/verify_required/connected/failed`，但后端路由绑定到插件登录管理器；不能直接视为 QQ、飞书、Telegram 的通用首次消息握手 API。
- [useWechatLogin.ts](../../frontend/src/modules/resources/composables/useWechatLogin.ts#L6) 展示了可参考的 1 秒轮询、取消、过期请求隔离和错误呈现；它的二维码/凭据归一化行为不应复用于这三个渠道。
- [channels-non-email.spec.ts](../../frontend/tests/e2e/channels-non-email.spec.ts#L12) 覆盖参数可见性、保存校验和 CRUD，没有开启握手测试；[channel-conversation.test.ts](../../frontend/tests/unit/channel-conversation.test.ts#L110) 只覆盖 `agent_enabled` 对话绑定区域的显隐。现有 [channels-headless.spec.ts](../../frontend/tests/e2e/channels-headless.spec.ts#L502) 测的是本地 `test` 渠道的双向处理，不是平台连接。

## 对用户要求的前端解释

通知单向模式开启时，前端应明确提示用户在等待期间向机器人私聊发送第一条消息，并轮询首次握手状态；服务端从该入站事件取得 chat 地址后，前端显示固定成功文案“成功连接”。对话双向模式则沿用现有 `agent_enabled` 语义，但其传输方式由后端/插件按平台实现：QQ WebSocket，飞书与 Telegram 长轮询。单向发送协议由后端实现为 QQ HTTP API、飞书 webhook；首次握手仍需要复用能接收入站首条消息的公共生命周期/地址提取能力。

前端不应伪造成功状态：只有握手 API 返回 `connected`（且后端已完成目标地址保存）后才显示“成功连接”；失败需展示后端错误，等待状态需可取消或明确超时。握手请求需要使用已保存且受保护的凭据，并且界面应说明用户需发送单聊消息。

## 建议改动文件

- `frontend/src/modules/resources/ui/ChannelEditor.vue`：将开启动作与普通保存区分；单向首次开启展示发送首条私聊消息提示、等待/失败/成功状态；成功文案固定为“成功连接”。已有资源编辑时，禁用状态下普通保存不触发握手。
- `frontend/src/modules/resources/composables/useChannelEditor.ts`：协调保存、启动握手、状态轮询和取消；复用 `useAsyncTask` 风格的错误状态，并避免旧实例/旧请求结果污染当前编辑器。不要在凭据尚未保护/保存前把明文凭据交给握手 API。
- `frontend/src/modules/resources/api/resourcesApi.ts`：待后端定义通用握手契约后增加 start/status/cancel 方法和状态类型。不要把业务复用强行绑定到 `/channels/login/*` 的扫码登录命名。
- `frontend/src/pages/resources/ResourcesPage.vue`：若成功后弹窗关闭，需让握手反馈在关闭前可见；或者保存实例后保留编辑器至握手完成并刷新列表。
- `frontend/src/modules/resources/ui/ChannelList.vue`：若运行状态需在后续访问时仍可见，列表需显示已启用/等待首条消息/连接成功/失败等服务端状态；当前列表没有状态数据接口，是否需要这部分取决于后端状态是否持久化。
- `frontend/tests/unit/channel-conversation.test.ts` 或新增 `frontend/tests/unit/channel-handshake.test.ts`：覆盖 API 路径与 payload、首次开启 start→waiting→connected、固定成功文案、失败错误、取消/卸载后不再轮询、快速切换实例时忽略过期响应、双向模式不误走单向握手。
- `frontend/tests/e2e/channels-non-email.spec.ts` 或新增握手 e2e：对 QQ/飞书/Telegram 分别模拟用户等待时发送第一条消息，验证提示、状态轮询及“成功连接”；再覆盖失败/取消和单向/双向分支。沿用 `channels-headless` 的隔离本地后端模式，不调用真实平台。

## 后端契约前置条件

目前前端已有的 `POST /api/channels`、`PUT /api/channels/{id}` 只保存资源；`/api/channels/{id}/conversation` 只管理 Agent 对话绑定。通用首次握手需要后端先定义可启动/查询/取消的会话 API，以及状态中的平台类型、等待消息、成功/失败和错误信息。若状态仅存在于进程内，页面刷新后的列表状态需要明确显示为未知或通过新的状态查询恢复，不能从 `enabled=true` 推断连接成功。

另一个需跨层确认的点：当前飞书适配器使用 WebSocket 接收事件，而用户要求双向飞书保持长轮询；QQ 的现有适配器也已拆开通知发送与接收生命周期。前端只能表达模式和握手结果，无法落实 HTTP API/webhook/WebSocket/长轮询选择，这部分必须在后端/插件实现及集成测试中验证。

## 本次实现记录

按照 `connect-channels-and-separate-builtin-plugins/design.md` 已实现前端握手流程：

- `resourcesApi` 增加 `POST/GET/DELETE /channels/{id}/connection`，状态类型严格使用 `idle/connecting/waiting_message/connected/failed/cancelled`，保留结构化错误和 `target_options`。
- `useChannelEditor` 保存 `enabled=true` 的 QQ、飞书、Telegram 后启动连接；按 1 秒查询，等待首条私聊消息；connected 后重新 GET 渠道资源并把目标回填草稿。新资源先 create，后续失败重试对同一 ID 使用 replace，不重复 create。
- 编辑器持续展示“等待首条私聊消息”、错误和“成功连接”；成功状态需要点击“完成”才关闭编辑器并 emit saved。账号参数变化、停用、切换渠道、关闭等待中的编辑器都会发 DELETE，并通过 generation 忽略迟到结果。保留高级目标字段，但首次连接不要求手填地址。
- 前端优先识别能力 schema 的 `x-workflowweave-first-message: true`；为兼容当前平台能力声明，QQ/飞书/Telegram 名称也作为同等明确的产品能力标记。待主线 schema 全部加入标记后可删除名称兜底。

API 假设：后端已提供上述三条连接路由；POST 是幂等启动/复用；GET/DELETE 返回同一状态结构；connected 时渠道资源 GET 已包含持久化目标，前端仍合并 `target_options` 以覆盖事件刚确认的地址。连接状态和目标保存由后端唯一负责，前端不直接处理平台协议。

验证：`frontend/tests/unit/channel-handshake.test.ts` 4 tests passed，`channel-conversation.test.ts` 5 tests passed；`vue-tsc --noEmit` 和 `npm run build` passed；新增 `frontend/tests/e2e/channel-handshake.spec.ts` 使用 Playwright 隔离路由分别模拟 QQ、飞书、Telegram 的 waiting→connected，验证首条消息提示、轮询、目标回填、成功连接和完成关闭，定向 smoke passed。测试未调用真实平台。
