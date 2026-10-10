## ADDED Requirements

### Requirement: Third-party WeChat notification transport
The wechat_openclaw channel SHALL send notifications through the user-configured WeClawBot-API HTTP service without installing OpenClaw or a Node SDK. It SHALL declare only the notification capability supported by the upstream public API.

#### Scenario: Authorized notification
- **WHEN** a valid service URL, bot ID and credential reference are configured
- **THEN** the channel SHALL POST JSON text to /bots/{bot_id}/messages using Bearer authentication and SHALL report success only for HTTP 200 with integer JSON code 200

#### Scenario: Unsupported legacy configuration
- **WHEN** old Node bridge parameters or unsupported target overrides are supplied
- **THEN** configuration or delivery SHALL explicitly fail without silently choosing a destination

#### Scenario: Ambiguous delivery
- **WHEN** an HTTP timeout, disconnect, 5xx response or invalid success response occurs
- **THEN** delivery SHALL be marked uncertain and SHALL not be automatically resent

### Requirement: Visible third-party risks and initialization limits
The channel editor SHALL display the third-party project's risks and actual initialization instructions without presenting an unsupported web login or Agent conversation capability.

#### Scenario: Configure WeChat
- **WHEN** the user selects wechat_openclaw
- **THEN** the editor SHALL identify WeClawBot-API as a community project, warn about credential/message handling and availability/account risks, link the project, explain terminal QR login and secure API token configuration, and state the ten-replies-per-context_token platform limit
