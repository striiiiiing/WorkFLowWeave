# Checkpoint、阶段重跑与子图清理

## Purpose

明确 Workflow 的原轮次中断续跑、父图阶段重跑及完成子图内部进度清理行为，保证恢复入口可验证、新旧执行轮次可区分，并保留历史查询、业务回执和 Agent 主动读取的语义。

## ADDED Requirements

### Requirement: 子图调用内的中断恢复

系统 SHALL 为每次子图调用采用 per-invocation 持久化，保留内容与进度直到父图可靠接收其结果且归档交接完成；同一轮进程中断续跑以 checkpoint/pending writes 复用已持久化成功任务，不查询 SessionStore 决定执行，调用之间不共享上一轮的活动进度。

#### Scenario: 并行子图执行中进程退出

- **WHEN** 子图部分任务已经保存成功结果而其他任务仍在执行时进程退出
- **THEN** 原 session 续跑使用该次子图进度，复用已保存结果，不把它当作一次全新的子图调用

#### Scenario: 业务失败已经正常返回

- **WHEN** 子图按 continue 策略汇总 failed 结果并正常结束
- **THEN** 不带 stage 的 resume 不自动重试该业务节点，用户可选择其所属父图阶段重跑

#### Scenario: 业务已完成但流归档未完成

- **WHEN** 图执行已到终态，而某些已提交结果尚未归档
- **THEN** 系统只从保留的执行事实补齐归档，不为补齐而重新执行已完成节点或通知

#### Scenario: 外部调用返回但任务尚未提交

- **WHEN** 采集或模型调用返回后、对应 checkpoint/pending writes 成功保存前进程退出
- **THEN** 续跑可能再次执行未持久化任务，不承诺业务归档替代执行提交；通知仍遵守 intent/receipt 的不确定投递边界

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

系统 SHALL 保持原 session/thread 身份，为每次主动阶段重跑持久化新的执行轮次并在 checkpoint 保留期内保留受支持的父图阶段入口；固定业务版本的正文遵循各自分类保留期，不要求永久保留 checkpoint。一次已受理请求的中断续跑不得再次分配投递轮次。

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

系统 SHALL 通过真实父图 checkpoint 确定阶段入口，从中取得原配置及必要上游内容，并以正确前驱创建新轮次后继续到 finish；拒绝其他 session、子图内部或图版本不兼容的 checkpoint，不根据归档标签猜测起点，也不从 SessionStore 重建执行 state。

#### Scenario: 下游旧正文未保存

- **WHEN** 用户从未过期的 analyze 入口重跑，原配置和采集输入仍可用，但旧分析或最终正文没有长期备份
- **THEN** 系统可以重新计算该阶段及下游，不因为将被重做的旧正文缺失而拒绝

#### Scenario: 上游输入或父图入口不可用

- **WHEN** 所选阶段的入口 checkpoint 或必需上游输入缺失
- **THEN** 系统明确拒绝并说明原因，不重新采集补齐、不退回另一轮历史

#### Scenario: 长期备份关闭但 checkpoint 完整

- **WHEN** 原配置或上游正文未长期备份，而有效阶段入口中原配置和内容仍完整
- **THEN** 系统可使用 checkpoint 重跑，不因为长期归档标记 not_saved 而拒绝；历史读取仍遵循备份开关

#### Scenario: checkpoint 已清理但归档尚在

- **WHEN** 所选阶段入口及其恢复依赖已被清理，长期业务归档仍可读取
- **THEN** 系统明确报告该入口不可 resume，归档只供历史读取，不自动引入第三种从归档重建执行的模式

### Requirement: defer 统一清理已完成子图内部进度

系统 SHALL 在父图全部业务节点结束后，由原生 defer 节点补齐归档并统一清理本 session 所有子图 namespace 的 checkpoint 和关联 pending writes；不得由外部流消费者逐阶段触发删除。清理不得删除未归档的最后副本、活动执行/恢复的调用、尚在保留期内的父图阶段入口及其 saver 依赖，或业务历史与回执。阶段 resume SHALL 不成为无限保留父图入口的理由。

#### Scenario: 子图结果已流出但父图尚未提交

- **WHEN** 消费者已看到子图完成事件，而父图结果 checkpoint 尚未确认提交
- **THEN** 该子图内部进度仍保留，不因收到 stream chunk 就进入删除

#### Scenario: 父图已经可靠接收结果

- **WHEN** 全部业务节点结束，父图已持久化结果，且内部独有内容和事实均已归档或按备份策略提交 not_saved/摘要
- **THEN** defer 节点统一删除所有非空子图 namespace 的 checkpoint 和 writes，保留父图入口与可读业务结果

#### Scenario: 父图只有汇总但单项未归档

- **WHEN** 父图已接收汇总，而某个独立分支内容仅在待删的子图 checkpoint/writes 中存在且未完成归档
- **THEN** 系统保留源数据并补齐归档，不因父图提交、队列为空或前端收到事件而认为交接完成

#### Scenario: 归档成功后删除前进程退出

- **WHEN** 长期归档事务已提交，而源 checkpoint 尚未删除时进程退出
- **THEN** 恢复原图的 pending defer 节点后幂等核对归档并继续清理，不新增业务版本或丢失内容

#### Scenario: 清理与恢复交错

- **WHEN** 恢复与清理可能访问同一 invocation
- **THEN** 系统在同一互斥边界核对引用关系，不删除活动恢复所需的内部进度

#### Scenario: 清理失败或进程退出

- **WHEN** defer 清理发生存储错误，或者节点尚未处理时进程退出
- **THEN** 系统向外报告错误并保留原生恢复位置；已提交业务结果仍可查询，未实际删除的数据不标为已释放

#### Scenario: 子图清理后主动阶段重跑

- **WHEN** 用户从保留的父图阶段入口重跑，而上一轮子图内部 checkpoint 已删除
- **THEN** 系统创建新的子图调用并执行至 finish，不要求已清理的内部任务历史

#### Scenario: 选择性清理父图历史

- **WHEN** 系统清理冗余父图历史，同时仍对外保留某个阶段入口
- **THEN** 系统保留该入口完整的 saver 恢复依赖；无法可靠确定依赖时保留数据并报告限制，不盲删关联记录

### Requirement: Checkpoint 独立过期与恢复边界

系统 SHALL 在 storage 所有的 BackupPolicy 内为 checkpoint 单独配置保留期，默认 7 天，父图阶段入口同样适用，不要求与正文期限满足固定大小关系。到期后 SHALL 明确报告 checkpoint_expired、停止接受依赖该入口的新 resume，并在归档交接完成且无活动执行依赖时清理；历史正文仍按各自保留期可读。物理删除延迟不得被解释为入口仍可使用。

#### Scenario: 报告永久保留但 checkpoint 已过期

- **WHEN** 用户读取旧报告或请求从该轮阶段重跑，而 checkpoint 已到期
- **THEN** 未过期报告继续可读，resume 返回明确过期原因及恢复期限，不从报告或其他归档重建执行图

#### Scenario: 到期时仍有未归档内容

- **WHEN** checkpoint 已到期，但归档失败使它仍持有唯一内容副本
- **THEN** 保留物理源数据、报告交接延迟并补齐归档；不因到期丢失内容，也不继续开放过期入口

#### Scenario: 清理与已受理恢复或新轮次交错

- **WHEN** 旧轮次到期，原 session 存在已受理执行或尚未到期的新轮次
- **THEN** 清理保护活动依赖和新轮次数据，不直接删除整个 thread；旧期限不被重跑自动延长

### Requirement: Agent 主动读取方式保持不变

系统 SHALL 保持 Agent 通过 sessionID 主动读取 Workflow 结果的既有方式；一次读取使用固定业务版本，不把 Workflow checkpoint 或新轮次自动注入已有 Agent 对话。

#### Scenario: Agent 读取后 Workflow 再次重跑

- **WHEN** Agent 已按某业务版本读取结果，随后 Workflow 完成新一轮执行
- **THEN** 原 Agent 会话不会被自动替换上下文，后续新的主动读取可按既有规则读取相应结果

### Requirement: 前端区分中断续跑与阶段重跑

前端 SHALL 分别提供原轮次中断续跑和 collect、analyze、aggregate、notify 阶段重跑交互，依据服务端对相应入口及材料的检查展示可用性和原因。阶段重跑 SHALL 明示所选阶段及后续流程会重新执行、经过通知阶段会再次发送，并在原 session 中跟踪服务端确认的新轮次。

#### Scenario: 继续中断运行

- **WHEN** 用户对服务端确认可续跑的中断运行选择继续
- **THEN** 请求不指定重跑阶段，继续跟踪原轮次，不创建新运行或再次发送本轮已确定投递

#### Scenario: 对完成运行重新通知

- **WHEN** 已完成运行的 notify 入口和冻结输出仍可用，用户选择从通知阶段重新执行
- **THEN** 页面显示再次发送说明，受理后跟踪原 session 的新轮次通知及 finish，不重复采集和分析

#### Scenario: 已返回的业务失败

- **WHEN** 一个业务项返回 failed 并已正常结束，用户希望重新计算
- **THEN** 页面引导选择所属父图阶段重跑，不把无 stage 续跑或单项重试展示为能够重做该项的操作

#### Scenario: 重跑不可用或请求结果未知

- **WHEN** 入口材料不可用、图版本不兼容、已有执行冲突，或提交后网络中断导致受理结果未知
- **THEN** 页面显示具体错误；结果未知时查询核对当前运行，不自动重发重跑请求并造成新的通知投递

#### Scenario: 中断不执行 deferred 清理

- **WHEN** 节点发生未被业务接口处理的执行异常、被取消或发生原生 interrupt
- **THEN** 不假设 defer 是 finally，不清理未结束子图，保留原 checkpoint/pending writes 供恢复
