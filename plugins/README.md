# LogAgent Plugins

具体适配器通过插件目录发现，核心不自动注册这些能力。每个包包含
`plugin.json`、注册入口 `main.py` 和实现文件。

| 目录 / 插件 ID | kind | 能力 name |
| --- | --- | --- |
| mock | collector | mock |
| logs | collector | logs |
| history | collector | history |
| mock_file | channel | mock |
| email | channel | email |
| qq | channel | qq |
| test_channel | channel | test |

资源继续使用原来的能力 name，因此文件通知的 `channel="mock"` 不变。
插件启停配置使用插件 ID，例如：

```json
{
  "channel": {
    "email": {"enabled": false},
    "mock_file": {"enabled": true}
  },
  "collector": {
    "mock": {"enabled": false}
  }
}
```

将该配置放在系统配置 `plugin_dir` 指向目录的 `config.json`，重载后生效。
部署或使用自定义 `plugin_dir` 时，将需要的插件包复制到对应目录；空目录
不会补装这些能力。Collector 保留既有兼容契约，新建来源仍采用 MCP/CLI。

Web 会话入口属于应用装配，留在核心。Manager、队列、投递上下文与
协议属于通用运行机制，也留在核心。
