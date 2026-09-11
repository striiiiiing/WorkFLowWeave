## Purpose

以轻量异步插件接入多个可配置来源，提供来源专属 schema 和 Setter，确保用户可以区分来源故障与无数据，并将历史内容安全地作为新的分析输入。

## ADDED Requirements

### Requirement: 插件发现与错误隔离

系统 SHALL 自动发现 Collectors 目录插件，允许一文件注册多个来源，重复、导入失败或无效声明必须有可识别错误且不破坏其他插件。

#### Scenario: 局部插件故障

- **WHEN** 一个插件先注册后抛异常，另一个有效
- **THEN** 故障文件的所有临时注册撤销，有效文件仍可用

### Requirement: 来源状态与 Setter

系统 SHALL 提供 mock、logs、history 来源，执行其声明的字段选择、过滤、分组、排序及计数能力，并区分失败、原始为空和处理后为空。

#### Scenario: 过滤后为空

- **WHEN** 来源有条目但全部被过滤
- **THEN** 返回 filtered_empty 并保留原始计数

#### Scenario: 无声明的能力

- **WHEN** 为不支持分组的插件设置分组
- **THEN** 保存或运行前拒绝设置

#### Scenario: 慢来源

- **WHEN** 采集超过超时
- **THEN** 返回 timeout，其他来源可以完成

### Requirement: 有界历史读取

历史来源 SHALL 支持指定 Workflow、最近次数、时间范围与 token 限制，按记录边界截取或报超限，并且不得重新执行原始来源。

#### Scenario: 没有历史

- **WHEN** 匹配范围内没有已存内容
- **THEN** 返回明确 empty，不伪造文字

#### Scenario: 超限

- **WHEN** 历史内容超过所选 token 上限
- **THEN** 按配置截取完整记录或报告超限，返回所用计数方法和截取事实
