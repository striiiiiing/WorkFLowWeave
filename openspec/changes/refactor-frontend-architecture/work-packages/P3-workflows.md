# P3 工作流闭环

根任务：[tasks.md §4](../tasks.md#4-p3--工作流闭环)。依赖 P2 已冻结的资源编辑器/gateway；可与 P4/P6 并行。依据：[原设计](../../design-frontend-architecture/design.md) §3.4、§5.3、§6。

## 文件所有权与边界

写 `modules/workflows/**`、`pages/workflows/**`、工作流 unit 测试；迁移/删除旧 WorkflowsView/WorkflowEditView、components/workflow、domain/workflow 和遗留工作流 type 出口。P1 列表控制器、使用位置 API 和 runs 最小 trigger/cancel 页面动作控制器（含实现）已供本包消费，保持公开签名或先与消费者协商；P4 后续只在该契约上接入完整运行控制器。不得编辑 resources 内部或 app 路由公共文件。

useWorkflowEditor 唯一拥有 sources/analyses/fan_in/channels/overrides 草稿。基本信息、阶段导航、来源/分析/汇聚/通知独立 SFC；SourceStepCard 继续分为来源选择/绑定列表/绑定项/配置编辑。子组件只读切片并发命名动作，不直接改嵌套 props，不双向 watch 同步整份草稿。

来源异步操作协调者调用 P2 gateway 和草稿动作；它不能另存完整工作流。脱离必须调用后端 resolve，前端不复制模板/覆盖合并规则；共享写入成功后精确 refresh，独立保存只改当前草稿。恢复共享/发布保持原确认行为，资源成功与工作流未保存分别显示。

## 验收与提交

覆盖阶段往返、任务 ID 中间输入/合法唯一改名引用更新、汇聚关闭保留编辑值且提交按 null 语义、目录刷新保留草稿、窗口返回监听清理、过期请求、停用绑定/稀疏覆盖/显式空值。列表运行操作调用 P1 已实现并冻结的 runs 公共动作能力，由页面装配；P3 不导入 runs 内部，不依赖 P4 才能运行；P4 在保持已冻结契约的基础上扩展能力。

提交可拆草稿纯逻辑与编辑闭环两批，任何批次保持旧/新路由只有一个实际实现。最终按单测→type/边界→build→新增/共享/独立/保存回读的真实浏览器闭环提交，记录与 P2 契约一致的证据。

## 实施证据

待填实际草稿动作/公开出口、测试结果、浏览器流程、commit 和删除清单。
