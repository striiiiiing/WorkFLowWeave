import {createInterface} from "node:readline";
import {parseArgs} from "node:util";
import {WeixinBridge} from "./bridge-core.mjs";

const emit = (message) => process.stdout.write(`${JSON.stringify(message)}\n`);
const {values} = parseArgs({options: {
  "account-id": {type: "string"}, "state-dir": {type: "string"},
}});
let bridge;
try {
  const {sdkRuntime, STORAGE_KEYS, sendText} = await import("./sdk.mjs");
  const runtime = sdkRuntime(values["state-dir"]);
  const account = await runtime.storage.get(STORAGE_KEYS.CREDENTIALS);
  if (!account?.token || !account.accountId || !account.baseUrl) throw new Error("weixin_login_required");
  if (account.accountId !== values["account-id"]) throw new Error("weixin_account_mismatch");
  await runtime.contexts.load();
  const sdk = {
    loadCursor: async () => (await runtime.storage.get(STORAGE_KEYS.CURSOR)) ?? "",
    saveCursor: (cursor) => runtime.storage.set(STORAGE_KEYS.CURSOR, cursor),
    poll: (cursor, signal) => runtime.api.getUpdates(account.baseUrl, account.token, cursor, signal),
    normalize: async (raw) => {
      const incoming = runtime.parser.parse(raw);
      runtime.contexts.remember(raw);
      await runtime.contexts.flush();
      if (!incoming || !["text", "voice"].includes(incoming.type) || !incoming.text?.trim() ||
          !incoming.userId || raw.message_id === undefined || raw.message_id === null) return null;
      return {message_id: `${account.accountId}:${incoming.userId}:${raw.message_id}`,
        text: incoming.text, conversation_kind: "weixin", conversation_id: incoming.userId,
        sender_id: incoming.userId};
    },
    send: (to, text, timeoutMs) => sendText(runtime, account, to, text, timeoutMs),
  };
  bridge = new WeixinBridge(sdk, emit);
  emit({type: "ready", protocol_version: 1, account_id: account.accountId});
} catch (error) {
  const code = ["weixin_login_required", "weixin_account_mismatch"].includes(error.message)
    ? error.message : "weixin_bridge_init_failed";
  emit({type: "fatal", code, exception_type: error.name});
  process.exit(1);
}
const input = createInterface({input: process.stdin});
input.on("line", (line) => {
  Promise.resolve().then(() => bridge.command(JSON.parse(line))).catch((error) => {
    emit({type: "fatal", code: "weixin_bridge_protocol_failed", exception_type: error.name});
    input.close();
    process.exitCode = 1;
  });
});
input.on("close", async () => {await bridge.stop();});
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => input.close());
