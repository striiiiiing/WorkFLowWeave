## ADDED Requirements

### Requirement: 可选资源编号前缀
插件 SHALL 可以声明可选 id_prefix；声明只含既有编号字符且不超过 43 位。自动编号按前缀、下划线及 UUID 组合，使用者编号不要求遵循该前缀。

#### Scenario: 非法前缀声明
- **WHEN** 插件声明非法字符或过长前缀
- **THEN** 注册产生明确诊断，不传播不可保存的自动编号

### Requirement: 声明式结果报告
采集插件 SHALL 可以返回可校验的 text、metrics、table 报告分段；系统随结果存档并在结果页展示，不执行插件脚本。

#### Scenario: 合法自定义报告
- **WHEN** 插件返回带标题的指标与表格
- **THEN** 页面按声明展示，提供给 AI 的输入仍来自标准 text

#### Scenario: 非法报告
- **WHEN** 插件声明未知报告类型或不匹配的表格列数
- **THEN** 采集结果报告明确的插件输出错误
