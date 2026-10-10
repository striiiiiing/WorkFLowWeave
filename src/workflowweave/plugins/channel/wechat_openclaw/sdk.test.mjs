import test from "node:test";
import assert from "node:assert/strict";
import {mkdtemp, stat} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {sdkRuntime, STORAGE_KEYS} from "./sdk.mjs";

test("the pinned SDK runtime persists credentials and context in the selected directory", async () => {
  const stateDir = await mkdtemp(join(tmpdir(), "workflowweave-wechat-"));
  const runtime = sdkRuntime(stateDir);
  await runtime.storage.set(STORAGE_KEYS.CREDENTIALS, {
    token: "secret", accountId: "bot", baseUrl: "https://example.test",
  });
  await runtime.contexts.load();
  runtime.contexts.set("user", "context");
  await runtime.contexts.flush();
  assert.equal((await runtime.storage.get(STORAGE_KEYS.CREDENTIALS)).token, "secret");
  assert.equal((await runtime.storage.get(STORAGE_KEYS.CONTEXT_TOKENS)).user, "context");
  assert.equal((await stat(join(stateDir, "credentials.json"))).mode & 0o777, 0o600);
});
