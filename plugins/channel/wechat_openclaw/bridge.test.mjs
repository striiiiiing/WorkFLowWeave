import test from "node:test";
import assert from "node:assert/strict";
import {setImmediate} from "node:timers/promises";
import {WeixinBridge} from "./bridge-core.mjs";

test("cursor advances only after Manager acknowledges admission", async () => {
  const events = [];
  const saved = [];
  let polls = 0;
  const sdk = {
    loadCursor: () => "old",
    saveCursor: (value) => saved.push(value),
    normalize: (value) => value,
    poll: async (_, signal) => {
      if (polls++ === 0) return {ret: 0, get_updates_buf: "new", msgs: [{message_id: "m", text: "hi"}]};
      return new Promise((resolve) => signal.addEventListener("abort", () => resolve({msgs: []}), {once: true}));
    },
  };
  const bridge = new WeixinBridge(sdk, (event) => events.push(event));
  await bridge.command({type: "start_receiving", request_id: "start"});
  await setImmediate();
  assert.equal(events.find((event) => event.type === "message").message_id, "m");
  assert.deepEqual(saved, []);
  await bridge.command({type: "inbound_ack", message_id: "m", status: "accepted"});
  await setImmediate();
  assert.deepEqual(saved, ["new"]);
  await bridge.command({type: "stop_receiving", request_id: "stop"});
  assert.equal(bridge.receiver, null);
});

test("SDK send success is acknowledged; missing receipt is uncertain", async () => {
  const events = [];
  const sent = [];
  const bridge = new WeixinBridge({send: async (...args) => {
    sent.push(args);
    return args[1] === "ok" ? {messageId: "sdk-id"} : {};
  }}, (event) => events.push(event));
  for (const text of ["ok", "missing"]) {
    await bridge.command({type: "send", request_id: text,
      route: {kind: "weixin", target: "peer"}, text, timeout_ms: 30000});
  }
  assert.deepEqual(sent[0], ["peer", "ok", 30000]);
  assert.equal(events[0].status, "sent");
  assert.equal(events[1].type, "error");
  assert.equal(events[1].uncertain, true);
});

test("rejected admission keeps the old cursor and exposes receiver failure", async () => {
  const events = [];
  const saved = [];
  const bridge = new WeixinBridge({
    loadCursor: () => "old", saveCursor: (value) => saved.push(value), normalize: (value) => value,
    poll: async () => ({ret: 0, get_updates_buf: "new", msgs: [{message_id: "m", text: "hi"}]}),
  }, (event) => events.push(event));
  bridge.start();
  await setImmediate();
  await bridge.command({type: "inbound_ack", message_id: "m", status: "rejected"});
  await setImmediate();
  assert.deepEqual(saved, []);
  assert.equal(events.at(-1).type, "receiver_error");
  await bridge.stop();
});

test("stop during admission does not advance cursor and accepts an in-flight ack", async () => {
  const saved = [];
  const events = [];
  const bridge = new WeixinBridge({
    loadCursor: () => "old", saveCursor: (value) => saved.push(value), normalize: (value) => value,
    poll: async () => ({ret: 0, get_updates_buf: "new", msgs: [{message_id: "m", text: "hi"}]}),
  }, (event) => events.push(event));
  bridge.start();
  await setImmediate();
  await bridge.stop();
  await bridge.command({type: "inbound_ack", message_id: "m", status: "accepted"});
  assert.deepEqual(saved, []);
  assert.equal(events.some((event) => event.type === "receiver_error"), false);
});
