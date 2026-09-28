# 父图恢复查询与直接编译子图

## 决策依据

用户明确指出 `aget_state()` 用于读取执行状态，不用于驱动恢复；当前恢复逻辑只消费父图的 values、next、config，不消费嵌套 task.state，因此不需要 `subgraphs=True`。用户要求移除 analyze 子图的 `copy(update={"stream_channels": compiled.output_channels})`，改用普通编译图。collect/notify 有相同覆盖，一并移除，避免同类子图装配不一致。此前任务文件记录的覆盖方案仅作为历史实验，不再是当前设计依据。

`astream_events(..., subgraphs=True)` 负责输出子图事件，与只读的 `aget_state()` 参数职责不同，继续保留。恢复仍由 LangGraph 使用父图 checkpoint/pending writes 和 `astream_events(None)` 执行，不读取嵌套 task.state 选择任务。

## 实施与验证

- [x] 恢复准备和执行器的 `aget_state()` 只读父图。
- [x] collect/analyze/notify 的单项及阶段子图直接编译，不覆盖 stream_channels。
- [x] 实际全链路复现并行子图在 session_id 的 LastValue 冲突；加入相等校验 reducer，阶段重跑用 Overwrite 更新 epoch，分析正文输入改为局部键。LangGraph 的 str 聚合通道初值为空串，首次写入需接受真实身份。
- [x] 阶段重跑的原生 pending write 保存 `Overwrite` 对象；归档补扫在读取该条 epoch 写入时取其 value，父图 checkpoint channel 值仍由 LangGraph 保存为字符串。
- [x] Luna max 验证普通编译图的完整 Workflow 执行、并行 reducer、归档、取消/中断恢复与阶段重跑；测试不再依赖嵌套 task.state。完整 Workflow 定向 9 项、阶段重跑 11 项通过。四个真实进程强退场景各自通过：分析中断只续未完成分支 18.01 秒，发送后回执未确认不重发 28.61 秒，已提交事实复用采集 23.30 秒，新 epoch 强退续跑 19.33 秒。整份进程套件一次运行超过 60 秒硬限，按场景拆分完成覆盖。
- [x] 原生 LangGraph 事件与 Runtime API 探针分别通过 2 项和 4 项，尚不足以替代完整 Workflow 链路回归。
- [x] Ruff 检查 Workflow 源码及本轮调整的清理、流进度、生命周期测试通过；`git diff --check` 和 OpenSpec 严格校验通过。逐处核对 `aget_state()` 只读父图、事件流保留 `subgraphs=True`、子图无 `stream_channels` 覆盖。
- [x] Luna max 补测清理 6 项、流进度 7 项、生命周期准入单项、SessionStore 23 项与集成 2 项通过。旧清理测试已按 defer 失败传播和恢复语义更新；原整组 lifecycle 测试超过 60 秒硬限，未据此宣称整组通过。
