import {createRequire} from "node:module";
import {dirname, join} from "node:path";
import {pathToFileURL} from "node:url";
import {FileStorage, createLogger, ApiError, NoContextError} from "@wechatbot/wechatbot";

// These fine-grained services are not exported at the package root in 2.2.0.
// Pin the package and verify these boundaries with the real SDK contract tests.
const require = createRequire(import.meta.url);
const root = dirname(require.resolve("@wechatbot/wechatbot"));
const load = (path) => import(pathToFileURL(join(root, path)));
const [auth, protocol, transport, parser, context, sender, keys] = await Promise.all([
  load("auth/authenticator.js"), load("protocol/api.js"), load("transport/http.js"),
  load("message/parser.js"), load("messaging/context.js"), load("messaging/sender.js"),
  load("storage/interface.js"),
]);
export const STORAGE_KEYS = keys.STORAGE_KEYS;

export function sdkRuntime(stateDir) {
  const logger = createLogger({level: "info"});
  const storage = new FileStorage(stateDir);
  const http = new transport.HttpClient({logger, retryPolicy: {maxRetries: 0}});
  const api = new protocol.ILinkApi(http, "WorkFLowWeave/0.1.0");
  return {logger, storage, api, auth: new auth.Authenticator(api, storage, logger),
    parser: new parser.MessageParser(), contexts: new context.ContextStore(storage, logger)};
}

export async function sendText(runtime, account, to, text, timeoutMs) {
  if (!runtime.contexts.get(to)) {
    const error = new NoContextError(to);
    error.deliveryUncertain = false;
    throw error;
  }
  const signal = AbortSignal.timeout(timeoutMs);
  let accepted = 0;
  class SendHttp extends transport.HttpClient {
    request(options) {
      return super.request({...options, signal});
    }
  }
  class SendApi extends protocol.ILinkApi {
    async sendMessage(...args) {
      const result = await super.sendMessage(...args);
      if (!result || typeof result !== "object" || Array.isArray(result) ||
          (result.ret !== 0 && result.errcode !== 0)) {
        throw new Error("weixin_send_receipt_missing");
      }
      accepted += 1;
      return result;
    }
  }
  const http = new SendHttp({logger: runtime.logger, retryPolicy: {maxRetries: 0}});
  const api = new SendApi(http, "WorkFLowWeave/0.1.0");
  const service = new sender.MessageSender(api, runtime.contexts, runtime.logger);
  try {
    await service.sendText(account.baseUrl, account.token, to, text);
  } catch (error) {
    const rejected = error instanceof ApiError && (
      (error.httpStatus >= 400 && error.httpStatus < 500) ||
      (typeof error.errcode === "number" && error.errcode !== 0)
    );
    error.deliveryUncertain = accepted > 0 || !rejected;
    throw error;
  }
}
