import {createInterface} from "node:readline";
import {parseArgs} from "node:util";
import QRCode from "qrcode";

const {values} = parseArgs({options: {"state-dir": {type: "string"}}});
const emit = (event) => process.stdout.write(`${JSON.stringify(event)}\n`);
const input = createInterface({input: process.stdin});
let waiting;
input.on("line", (line) => {
  if (waiting && /^[0-9]{1,16}$/.test(line.trim())) {
    waiting(line.trim());
    waiting = undefined;
  }
});
let updates = Promise.resolve();
try {
  const {sdkRuntime, STORAGE_KEYS} = await import("./sdk.mjs");
  const runtime = sdkRuntime(values["state-dir"]);
  const previous = await runtime.storage.get(STORAGE_KEYS.CREDENTIALS);
  emit({state: "waiting", message: "正在获取微信二维码"});
  const account = await runtime.auth.login({force: true, callbacks: {
    onQrUrl: (url) => {
      updates = updates.then(async () => {
        if (!/^https:\/\/\S+$/.test(url)) throw new Error("weixin_qr_url_invalid");
        const image = await QRCode.toDataURL(url, {type: "image/png", width: 256, margin: 2});
        emit({state: "waiting", qr_url: url, qr_image: image, message: "用微信扫码并确认登录"});
      });
    },
    onScanned: () => {updates = updates.then(() => emit({state: "scanned", message: "已扫码，请在微信中确认"}));},
    onExpired: () => {updates = updates.then(() => emit({state: "waiting", qr_url: null,
      qr_image: null, message: "二维码已过期，正在重新生成"}));},
    onVerifyCode: (retry) => {
      updates = updates.then(() => emit({state: "verify_required",
        message: retry ? "数字不匹配，请重新输入手机微信显示的数字" : "请输入手机微信显示的数字"}));
      return new Promise((resolve) => {waiting = resolve;});
    },
  }});
  await updates;
  if (!account.token || !account.accountId) throw new Error("weixin_credentials_missing");
  if (previous?.token !== account.token) {
    for (const key of [STORAGE_KEYS.CURSOR, STORAGE_KEYS.CONTEXT_TOKENS, STORAGE_KEYS.TYPING_TICKETS]) {
      await runtime.storage.delete(key);
    }
  }
  emit({state: "connected", account_id: account.accountId, message: "登录成功，Token 已保存到本地"});
} catch (error) {
  emit({state: "failed", message: `微信登录失败（${error.name}），请检查网络、插件依赖及状态目录写权限`});
  process.exitCode = 1;
} finally {
  input.close();
}
