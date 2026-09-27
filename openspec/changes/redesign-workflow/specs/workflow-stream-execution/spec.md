# Workflow 流式执行

## ADDED Requirements

### Requirement: 统一的执行过程输出

系统 SHALL 从一次图执行中提供父图及子图的过程更新，关联 session、阶段和适用的任务身份；观察执行过程不得导致再次执行同一运行。

#### Scenario: 分支乱序完成

- **WHEN** 多个采集或分析任务以不同顺序完成
- **THEN** 消费者可分别观察结果，最终整理顺序仍遵循配置，而非流到达顺序

#### Scenario: 观察者断开

- **WHEN** 一个进度观察者断开而用户没有请求取消
- **THEN** 已提交的后台运行继续，其他查询入口仍可读取真实状态

### Requirement: 选择必要业务事件实时推送

系统 SHALL 通过 `astream` 消费子模块，按 tags 所标识的业务类别选择 fan-out 单项成功、业务 fan-in 完成、aggregate 成功和逐渠道发送成功更新，及时推送前端；不得等待整个子图结束，也不得默认广播所有内部节点。事件 SHALL 关联 session、执行轮次、类别和稳定业务身份，允许协程调度及传输耗时。

#### Scenario: fan-out 快分支成功

- **WHEN** 某个采集或分析项完成必要业务提交，而另一个分支仍被阻塞
- **THEN** 前端在慢分支结束及 arrange 执行之前看到该项成功，最终列表仍保持配置顺序

#### Scenario: fan-in 完成

- **WHEN** 业务 fan-in 完成汇总
- **THEN** 前端收到一次对应结果更新，父子图重复暴露结果不生成重复条目或业务版本

#### Scenario: aggregate 成功

- **WHEN** aggregate 完成必要业务提交并冻结输出，包括关闭模型 fan-in、仅整理分支输出的情况
- **THEN** 前端收到一次 aggregate 成功更新，不等待 notify 完成

#### Scenario: fan-in 与 aggregate 完成点区分

- **WHEN** fan-in 和 aggregate 分别完成各自的业务工作
- **THEN** 分别推送对应完成结果；若两种分类实际指向同一个完成结果，则只推送一次并明确 aggregate 成功，不因分类去重而漏报该阶段完成

#### Scenario: 单渠道发送成功

- **WHEN** 一个 output/channel 投递项发送成功且确定回执已持久化，而其他渠道尚未完成
- **THEN** 前端立即进入可异步推送该项成功的路径，不等待整个 notify 子图完成

#### Scenario: 不推送内部节点

- **WHEN** 初始化、路由、intent 或仅负责排序的内部节点完成
- **THEN** 不因此生成前端业务完成事件，不将这些节点与业务 fan-in 混淆

#### Scenario: 业务失败或不确定投递

- **WHEN** 选定业务项返回 failed 或 delivery_uncertain
- **THEN** 前端收到相应错误或不确定状态，不因节点正常返回而显示成功

#### Scenario: 相同 tags 与订阅重连

- **WHEN** 多个分支共享分类 tags，或前端断线后重新订阅
- **THEN** 各项按稳定业务身份更新，重连用查询补齐已提交状态，不串项或重新执行原运行

### Requirement: 正文采用引用存储

系统 SHALL 将符合备份策略的正文保存在 SessionStore，checkpoint 和 pending writes 保存执行控制信息及正文引用；消费子模块 SHALL 复用既有结果，不再次保存完整正文或把 checkpoint ID 当作业务版本。

#### Scenario: 子图清理后的固定版本查询

- **WHEN** 已完成子图内部 checkpoint 被清理，业务正文仍在保留期内
- **THEN** Agent 和历史消费者仍可通过 SessionReader 读取指定业务版本的正文

#### Scenario: 旧正文过期

- **WHEN** 指定业务版本正文已过期，新轮次产生了新正文
- **THEN** 返回旧正文不可用，不用新正文替代或从 checkpoint 恢复旧正文副本

### Requirement: 独立任务恢复

系统 SHALL 保持逐来源、逐分析项的独立图任务边界，在同一轮进程中断续跑时复用已持久化成功结果。用户主动从阶段重跑时，目标阶段及后续任务重新执行；本要求不承诺单独重试一个已经正常返回 failed 的业务节点。

#### Scenario: 一个分支中断而另一个已经保存

- **WHEN** 进程在某个子图任务执行中中断，另一分支的成功结果已持久化，随后在原轮次续跑
- **THEN** 已保存成功结果被复用，未完成任务继续执行

#### Scenario: 恢复材料缺失

- **WHEN** 原 checkpoint 或必要的原配置、正文不可用
- **THEN** 恢复明确报告原因，不以重新采集或当前配置补齐旧运行

### Requirement: 执行事实与观察一致

系统 SHALL 以已提交的执行状态及业务事实提供查询，重复消费同一结果不得增加业务版本；不得以流事件到达替代持久化完成。

#### Scenario: 同一结果从父子图重复出现

- **WHEN** 消费者观察到指向同一已保存业务结果的多个更新
- **THEN** 查询只有该结果原有的业务版本，不产生第二份正文

#### Scenario: 必要持久化失败

- **WHEN** 恢复所需数据或必要管理事实无法提交
- **THEN** 系统显式记录或向调用方报告失败，不继续依赖未提交事实的新外部操作

### Requirement: 保持既有外部契约

系统 SHALL 保留已保存配置的执行含义、只读历史的固定业务版本及备份策略；本次内部图重构不要求 Collector、AI 或 Channel 插件改用新协议。

#### Scenario: 使用现有配置和历史消费者

- **WHEN** 已有 Workflow 执行，History Collector 或 Agent 接续读取指定版本的结果
- **THEN** 原提示词、输入顺序及查询语义保持有效，消费者不需要解释 checkpoint 私有表

#### Scenario: 某类正文关闭备份

- **WHEN** 配置禁止保存某类正文
- **THEN** 该正文不会通过父子 checkpoint、pending writes 或过程索引被间接持久化

#### Scenario: 旧运行执行位置与新图不兼容

- **WHEN** 旧 checkpoint 包含新图无法解释的节点或任务位置
- **THEN** 系统明确报告不兼容并保留历史，不猜测执行位置或自动重发通知
