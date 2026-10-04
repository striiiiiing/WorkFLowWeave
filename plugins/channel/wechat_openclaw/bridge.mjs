import {createRequire} from "node:module";
import {dirname, join} from "node:path";
import {pathToFileURL} from "node:url";
import {createInterface} from "node:readline";
import {parseArgs} from "node:util";
import {WeixinBridge} from "./bridge-core.mjs";

const emit = (message) => process.stdout.write(`${JSON.stringify(message)}\n`);
const {values} = parseArgs({options: {
  "account-id": {type: "string"}, "state-dir": {type: "string"},
}});
if (values["state-dir"]) process.env.OPENCLAW_STATE_DIR = values["state-dir"];

let bridge;
try {
  if (!values["account-id"]) throw new Error("account_id_missing");
  const require = createRequire(import.meta.url);
  const root = dirname(require.resolve("@tencent-weixin/openclaw-weixin/package.json"));
  const load = (path) => import(pathToFileURL(join(root, "dist/src", path)));
  const [accounts, api, inbound, send, sync] = await Promise.all([
    load("auth/accounts.js"), load("api/api.js"), load("messaging/inbound.js"),
    load("messaging/send.js"), load("storage/sync-buf.js"),
  ]);
  const account = accounts.resolveWeixinAccount({}, values["account-id"]);
  if (!account.configured) throw new Error("weixin_login_required");
  inbound.restoreContextTokens(account.accountId);
  const cursorPath = sync.getSyncBufFilePath(account.accountId);
  const sdk = {
    loadCursor: () => sync.loadGetUpdatesBuf(cursorPath) ?? "",
    saveCursor: (cursor) => sync.saveGetUpdatesBuf(cursorPath, cursor),
    poll: (cursor, signal) => api.getUpdates({baseUrl: account.baseUrl, token: account.token,
      get_updates_buf: cursor, abortSignal: signal}),
    normalize: (raw) => {
      const id = inbound.getWeixinMessageId(raw);
      const context = inbound.weixinMessageToMsgContext(raw, account.accountId, {});
      if (!id || typeof raw.from_user_id !== "string" || !raw.from_user_id ||
          typeof context.Body !== "string" || !context.Body.trim()) return null;
      if (raw.context_token) inbound.setContextToken(account.accountId, raw.from_user_id, raw.context_token);
      return {message_id: `${account.accountId}:${raw.from_user_id}:${id}`, text: context.Body,
        conversation_kind: "weixin", conversation_id: raw.from_user_id, sender_id: raw.from_user_id};
    },
    send: (to, text, timeoutMs) => send.sendMessageWeixin({to, text, opts: {
      baseUrl: account.baseUrl, token: account.token, accountId: account.accountId,
      contextToken: inbound.getContextToken(account.accountId, to), timeoutMs,
    }}),
  };
  bridge = new WeixinBridge(sdk, emit);
  emit({type: "ready", protocol_version: 1, account_id: account.accountId});
} catch (error) {
  emit({type: "fatal", code: error.message === "weixin_login_required" ? "weixin_login_required" : "weixin_bridge_init_failed",
    exception_type: error.name});
  process.exit(1);
}

const input = createInterface({input: process.stdin});
input.on("line", (line) => {
  // Concurrent commands let inbound acknowledgements progress while sends or
  // stopping a long poll are awaiting their SDK operation.
  Promise.resolve().then(() => bridge.command(JSON.parse(line))).catch((error) => {
    emit({type: "fatal", code: "weixin_bridge_protocol_failed", exception_type: error.name});
    input.close();
    process.exitCode = 1;
  });
});
input.on("close", async () => {await bridge.stop();});
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {input.close();});
}
