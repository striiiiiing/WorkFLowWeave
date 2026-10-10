# Feishu authentication event-loop blocking fix

## Basis And Root Cause

- User report: sending hello to the Feishu bot stalls the entire frontend.
- Scope follows ../../proposal.md and ../../design.md, especially first-message confirmation, the single ChannelManager, SDK HTTP delivery, and explicit cancellation/failure. The proposal and design are unchanged.
- Installed lark-oapi 1.7.3: api/im/v1/resource/message.py acreate (line 72) and areply (line 476) call synchronous verify before awaiting Transport.aexecute. core/token/manager.py get_self_tenant_token calls Transport.execute on a cache miss. core/http/transport.py execute calls requests.request. A cold or expired token therefore blocks the FastAPI loop when channel.py awaits the generated async route directly.
- The SDK Config defaults its synchronous HTTP timeout to 30 seconds. asyncio.timeout cannot interrupt synchronous network work on the loop, so the channel send budget alone does not prevent the stall.
- This is an adapter boundary fix shared by notification sends, first-message confirmation, and Agent replies. Agent resource capture and tokenizer concerns were investigated but are not established causes of this incident and are outside this patch.

## Implementation Decisions

- Call the SDK's existing verify on a worker thread, using a private Config copy and RequestOption. Keep the SDK token cache as the only token owner; add no cache or hand-written authentication protocol.
- After verify, use the official enable_set_token option on that private Config. The generated async API then consumes the explicit token locally and performs only its normal async HTTP delivery. This avoids a second network lookup even if a cached token expires between the two verification steps.
- Authentication uses the remaining ChannelConfig.timeout, sourced from the existing delivery deadline. No new timeout default is introduced.
- Keep in-flight authentication tasks owned by the adapter. Shield the worker from coroutine cancellation, await outstanding workers on stop, and dispatch the message only after an awaited authorization result. Cancellation or timeout cannot let the worker itself send a message later.
- Preserve original message IDs, async SDK create/reply routes, transport errors, no retry, and Manager delivery receipts.

## Work And Validation

- [x] Locate blocking SDK authentication with installed source evidence.
- [x] Fix create and reply through one authorization boundary.
- [x] Test real SDK cold-token authentication with a blocked requests transport and a concurrent FastAPI HTTP probe, for both create and reply.
- [x] Test cancellation/timeout before authorization completes: no delivery, stop waits for the worker.
- [x] Feishu targeted unit tests: 14 passed, with a 60-second command timeout.
- [x] Negative control: restore the previous direct-await path in memory only; both concurrent HTTP regressions fail as expected (2 failed in 27.60 seconds). The fixed path passes.
- [x] Adjacent regression: test_first_message_connection.py, test_platform_admission.py, test_channel_manager.py — 54 passed in 30.72 seconds; command hard timeout 60 seconds. Together with Feishu: 68 passed.
- [x] Ruff check of changed adapter and test file; git diff --check.
- [x] uv build --wheel --out-dir /tmp/logagent-feishu-20261010 succeeded.
- [x] Activate the fix through POST /api/reload?scope=plugins: HTTP 200, discovery errors empty. No process restart or configuration changes required.
- [x] Running-service smoke: /api/health, /api/channels, /api/agents/sessions, /api/plugins all HTTP 200, approximately 2.5–9.0 ms; health ready, existing Feishu conversation binding preserved.

No real platform message is sent by these regression tests. The installed SDK authentication and generated message routes are real; network transports are controlled test dependencies.
