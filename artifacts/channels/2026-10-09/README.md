# 真实渠道验证：2026-10-09

本目录保留当次平台结果，不代表后续 SDK 变更已通过真实账号验收。欠账只维护在 [渠道连接任务](../../../openspec/changes/connect-channels-and-separate-builtin-plugins/tasks.md)。

| 渠道 | 当次结果 | 证据 |
| --- | --- | --- |
| QQ | 一个实例连接；另一个返回 `100016`；未收到首条私聊，未验证回复 | [最终状态](conversation-final.json)、[拒绝结果](qq-final-retest.json) |
| 飞书 | 当时 SDK 握手成功，未收到私聊或验证回复；后续官方 Channel SDK 需另验 | [最终状态](conversation-final.json) |
| Telegram | polling 连接；未收到首条消息，主动目标仍 `chat not found` | [最终状态](conversation-final.json)、[目标验证](telegram-target.json) |
| 微信 | 代理诊断下取得 QR 并验证取消；未扫码、登录或验证收发 | [QR/取消结果](wechat-proxy-login.json) |

file 的真实追加与回读已有通过记录。连接、等待消息、平台接受发送与收到回复分别表达，不能互相替代。重复重试、旧浏览器诊断和已完成修复流水不再保留。

[run.py](run.py)保留真实验证入口，只在明确需要联网收发时运行；整理文件不会自动启动平台连接。用 `--mode conversation` 观察首条消息、`--channel` 限定实例；结果默认写入 Git 忽略的 `artifacts/local/channels/result.json`。个人配置与凭据只留在本地。
