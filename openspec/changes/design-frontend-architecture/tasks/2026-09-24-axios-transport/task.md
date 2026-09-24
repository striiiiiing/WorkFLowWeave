# HTTP 选型与状态方案修订

## 用户要求与范围

- 用户说明不熟悉 Query 库和 Pinia，本轮希望使用自己更熟悉的 Axios，并明确要求“重新写要求，尽可能把 fetch 给替代掉，改为用 axios”。
- 本轮据此修改 [design.md](../../design.md)：普通 HTTP 统一 Axios，暂不引入 Pinia/Query 库；继续使用 Vue 本地状态与已有组合函数。该选择依据维护者偏好，不再以“没有共享查询需求”解释。
- 仍遵守 [proposal.md](../../proposal.md) 的设计交付范围：不安装依赖、不改前端业务代码、不创建或切换分支。后续在独立分支实施。
- 依用户 SDD 约定新增本任务，保留首轮 [tasks.md](../../tasks.md) 和 [组件边界记录](../2026-09-24-component-boundaries/task.md)；其早期选型解释以本记录及新设计为准，不改写历史。

## 决策依据与默认值

| 决策 | 源码/需求依据 | 理由与边界 |
| --- | --- | --- |
| 统一 Axios HTTP 入口 | 用户本轮要求；`frontend/src/api/client.ts` 当前唯一应用 HTTP fetch；各模块都经过 request | shared/api 实例工厂与薄适配，应用装配注入；模块 API 保留端点/DTO，不并存 fetch 后备实现 |
| 暂不引入 Pinia/Query 库 | 用户对当前学习与维护成本的偏好 | 不否定库的作用；Vue ref/computed/composable 管作用域状态，同屏共享由同一个查询拥有者提供 |
| 显式共享与刷新 | `AgentsView.vue` 和 `AgentGlobalSettingsModal.vue` 分别查配置；`NotificationCard.vue`、`ResourceEditor.vue` 分别查 plugins；`AgentContinueButton.vue` 重新读取详情 | 页面提供同屏查询，保存后刷新该拥有者；跨页重新读取，不另造全局缓存或事件总线 |
| Agent 输入作用域保持稳定 | `App.vue` 以 route.path 为组件 key；`AgentsView.vue` inputs 映射需要跨会话路由保存 | Agent 路由采用共同页面 key，会话切换只替换查询/SSE，不销毁输入拥有者；离开 Agent 区域不新增持久化 |
| `/api` 与 timeout `0` | 当前 client.ts 同源前缀且没有统一浏览器超时 | 传输替换不引入任意 30 秒/300 秒执行限制；保留 AbortSignal，不自动重试有副作用请求 |
| 请求对象用 data/params | 当前 API 传入 RequestInit/body/JSON.stringify；Axios 请求配置 | 在同一传输迁移中调整，JSON 只序列化一次，保留路径编码、分页/筛选值和请求 ID |
| 错误与 503/204 行为不变 | `api.test.ts`、`system.ts` 和 client.ts 已有断言/实现 | 204 无正文；健康 503 报告可读但 error 信封失败；普通 4xx/5xx、非 JSON 错误和无效成功 JSON 明确失败 |
| 条件写入与版本读取保留 | `api/agents.ts` 的 If-Match/If-None-Match；`AgentFileDrawer.vue` 分页 hash 检查；runs phase 的 version 参数 | 避免 Axios 迁移破坏文件冲突、报告版本或未知提交结果语义 |
| SSE 与测试例外 | `useAgentStream.ts` 使用 EventSource；`tests/e2e/agent.spec.ts` 的 readSse 用 fetch 读取流并带 Last-Event-ID；route.fetch 是 Playwright 代理 | 保留流协议实现和测试探针；仅普通应用 HTTP 必须移除 fetch，不修改依赖内部或无关组件属性 |

2026-09-24 核对的官方 Axios 资料（用于请求边界设计，版本在实施时通过依赖锁文件固定）：

- 实例创建：`https://axios-http.com/docs/instance`，统一实例及配置。
- 请求配置：`https://axios-http.com/docs/req_config`，data/params、adapter、响应处理与超时。
- 取消：`https://axios-http.com/docs/cancellation`，AbortController/signal；本项目不改用 CancelToken。
- 错误处理：`https://axios-http.com/docs/handling_errors`，HTTP 响应错误与未收到响应的区别、可接受状态的配置。

## 本轮文档工作

- [x] 核对普通 HTTP、SSE、fetch 测试与既有状态/刷新机制。
- [x] 重写选型依据，撤回“没有共享状态需求”的推断。
- [x] 明确 Axios 入口、请求/响应契约、取消/错误、替换边界与测试例外。
- [x] 对齐状态所有权、迁移映射、阶段退出条件和验收矩阵。
- [x] 校验 OpenSpec、相对链接、空白和本轮差异并记录实际结果。

## 后续实施验收

以下为未来独立分支的要求，本轮尚未执行：

- [ ] 安装 Axios 并更新 package.json/package-lock.json；不新增 Pinia/Query 依赖。
- [ ] 在统一入口替换 fetch，所有模块请求改用 Axios 适配；不保留 RequestInit/body 作为长期接口。
- [ ] 迁移 api/runs/provider/agent-channel API 单测，验证取消、URL/JSON/条件头、错误/204/503、命令不自动重发。
- [ ] 按 design §5 共享同屏查询与显式刷新，真实路由验证 Agent 草稿作用域；不扩展成全局缓存。
- [ ] 静态检查普通 HTTP 无直接 fetch；原始 SSE 测试与 Playwright 例外保留注释和用途。
- [ ] 顺序通过目标单测、类型/静态检查、构建和最小真实浏览器烟测；原有未验收协议差异在实施基线中注明。

## 本轮验证记录

2026-09-24：`openspec validate design-frontend-architecture --strict --no-interactive` 通过（退出码 0）；本 change 的 5 份 Markdown、21 个相对链接、代码围栏和行尾空白检查通过；已核对上述官方资料并审查本轮与修改前副本的差异。本轮只修改架构设计并新增本任务，没有运行前后端测试，没有安装 Axios 或实现 HTTP 迁移，也没有切换分支。后续实施复选框保留未完成状态。
