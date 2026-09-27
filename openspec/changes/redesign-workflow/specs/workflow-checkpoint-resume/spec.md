# Checkpoint、阶段重跑与子图清理

## ADDED Requirements

### Requirement: 子图调用内的中断恢复

系统 SHALL 为每次子图调用保留独立的持久化进度，直到父图可靠接收其结果；同一轮进程中断续跑复用已持久化成功任务，调用之间不共享上一轮的活动进度。

#### Scenario: 并行子图执行中进程退出

- **WHEN** 子图部分任务已经保存成功结果而其他任务仍在执行时进程退出
- **THEN** 原 session 续跑使用该次子图进度，复用已保存结果，不把它当作一次全新的子图调用

#### Scenario: 业务失败已经正常返回

- **WHEN** 子图按 continue 策略汇总 failed 结果并正常结束
- **THEN** 不带 stage 的 resume 不自动重试该业务节点，用户可选择其所属父图阶段重跑

### Requirement: 从父图阶段重新执行到结束

系统 SHALL 允许用户在原 session 中选择 collect、analyze、aggregate 或 notify 的入口重新执行；保留前序结果，重做目标阶段全部任务及后续流程直到 finish，沿用原快照和失败路由，不只运行选定阶段。

#### Scenario: 从分析阶段重跑

- **WHEN** 用户从一个有效的 analyze 入口发起 resume
- **THEN** 系统复用该入口的采集输入，重新执行全部分析、汇总、通知和 finish；旧轮次的成功分析不使本轮跳过分析任务

#### Scenario: 从通知阶段重跑

- **WHEN** 用户从有效的 notify 入口发起 resume
- **THEN** 系统读取所选冻结输出，建立新轮次的通知意图并发送，再执行 finish，不重复采集或分析

#### Scenario: 新执行再次遇到停止条件

- **WHEN** 目标阶段重跑时命中既有 stop 或全空停止规则
- **THEN** 系统遵循该路由结束，不为到达后续阶段而忽略业务失败策略

### Requirement: 保留历史和明确的执行身份

系统 SHALL 保持原 session/thread 身份，为每次主动阶段重跑持久化新的执行轮次并保留旧 checkpoint 和业务版本；一次已受理请求的中断续跑不得再次分配投递轮次。

#### Scenario: 新一轮重跑后查询旧结果

- **WHEN** 新轮次已生成新的阶段结果
- **THEN** 固定旧业务版本的查询仍返回旧结果，新一轮结果和回执不会覆盖它

#### Scenario: 新轮次发送前后进程中断

- **WHEN** 主动重跑已经建立轮次后进程退出，随后接续该运行
- **THEN** 系统继续使用该轮次，同轮确定回执直接复用，不把此次续跑当成再次主动重跑

#### Scenario: 两个请求同时推进同一 session

- **WHEN** 一个执行已经受理，另一个独立 resume 请求同时到达
- **THEN** 系统明确报告运行冲突，不允许两个任务同时改变执行头或重复建立投递

### Requirement: 恢复入口和材料校验

系统 SHALL 通过父图 checkpoint 确定阶段入口，只使用原配置及必要上游输入；拒绝其他 session、子图内部或图版本不兼容的 checkpoint，不根据业务阶段标签猜测起点。

#### Scenario: 下游旧正文已过期

- **WHEN** 用户从 analyze 重跑，原快照和采集输入仍可用，但旧分析或最终正文已过期
- **THEN** 系统可以重新计算该阶段及下游，不因为将被重做的旧正文缺失而拒绝

#### Scenario: 上游输入或父图入口不可用

- **WHEN** 所选阶段的入口 checkpoint 或必需上游输入缺失
- **THEN** 系统明确拒绝并说明原因，不重新采集补齐、不退回另一轮历史

### Requirement: 异步清理已完成子图内部进度

系统 SHALL 在子图正常结束且父图已持久化其结果后，异步清理该次调用的内部 checkpoint 和关联 pending writes；清理不得删除仍用于中断恢复的调用、父图阶段入口或业务历史与回执。

#### Scenario: 子图结果已流出但父图尚未提交

- **WHEN** 消费者已看到子图完成事件，而父图结果 checkpoint 尚未确认提交
- **THEN** 该子图内部进度仍保留，不因收到 stream chunk 就进入删除

#### Scenario: 父图已经可靠接收结果

- **WHEN** 父图已保存阶段结果并不再依赖该次调用内部任务
- **THEN** 系统可异步删除该调用及已确认嵌套 namespace 的 checkpoint 和 writes，保留父图入口与可读业务结果

#### Scenario: 清理与恢复交错

- **WHEN** 恢复与清理可能访问同一 invocation
- **THEN** 系统在同一互斥边界核对引用关系，不删除活动恢复所需的内部进度

#### Scenario: 清理失败或进程退出

- **WHEN** 异步清理发生存储错误，或者候选尚未处理时进程退出
- **THEN** 系统报告清理失败或在下次核对时重新发现候选，已提交业务结果仍可查询，未实际删除的数据不标为已释放

#### Scenario: 子图清理后主动阶段重跑

- **WHEN** 用户从保留的父图阶段入口重跑，而上一轮子图内部 checkpoint 已删除
- **THEN** 系统创建新的子图调用并执行至 finish，不要求已清理的内部任务历史

### Requirement: Agent 主动读取方式保持不变

系统 SHALL 保持 Agent 通过 sessionID 主动读取 Workflow 结果的既有方式；一次读取使用固定业务版本，不把 Workflow checkpoint 或新轮次自动注入已有 Agent 对话。

#### Scenario: Agent 读取后 Workflow 再次重跑

- **WHEN** Agent 已按某业务版本读取结果，随后 Workflow 完成新一轮执行
- **THEN** 原 Agent 会话不会被自动替换上下文，后续新的主动读取可按既有规则读取相应结果
