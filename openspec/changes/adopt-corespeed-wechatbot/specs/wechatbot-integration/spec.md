## ADDED Requirements

### Requirement: Lightweight WeChatBot SDK integration
The WeChat channel SHALL use corespeed-io/wechatbot via pinned @wechatbot/wechatbot 2.2.0 without installing the full OpenClaw host. It SHALL support notifications, Agent conversations and webpage QR login using SDK-owned protocol operations.

#### Scenario: Web login completes
- **WHEN** the user scans the displayed QR and completes any numeric challenge
- **THEN** the SDK SHALL persist credentials locally before the Web API reports success, SHALL return only account and non-secret configuration data, and SHALL never include the token in IPC

#### Scenario: Message admission
- **WHEN** an incoming batch is received
- **THEN** its cursor SHALL be persisted only after Manager acknowledges each accepted or duplicate message

#### Scenario: Uncertain send
- **WHEN** a send times out, disconnects, loses its receipt or partially completes
- **THEN** the channel SHALL report uncertain delivery without implicit resend

### Requirement: Project attribution and requested UI
README.md SHALL identify and link corespeed-io/wechatbot. The frontend SHALL show login controls and the platform's ten-reply context limit without a third-party risk warning.

#### Scenario: Configure WeChat
- **WHEN** the user selects the WeChat channel
- **THEN** the editor SHALL offer QR login, cancellation and refresh, SHALL show the saved account when connected, and SHALL not show the removed third-party risk alert
