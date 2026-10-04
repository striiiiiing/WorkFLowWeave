// Transport glue only; Tencent's package owns iLink, authentication and cursors.
export class WeixinBridge {
  constructor(sdk, emit) {
    this.sdk = sdk;
    this.emit = emit;
    this.pending = new Map();
    this.controller = null;
    this.receiver = null;
  }

  async command(request) {
    if (request.type === "inbound_ack") {
      const pending = this.pending.get(request.message_id);
      if (!pending) {
        // stop_receiving can overtake an acknowledgement already in the pipe.
        if (!this.controller || this.controller.signal.aborted) return;
        throw new Error("unexpected_inbound_ack");
      }
      this.pending.delete(request.message_id);
      if (["accepted", "duplicate"].includes(request.status)) pending.resolve();
      else pending.reject(new Error("manager_enqueue_rejected"));
      return;
    }
    if (typeof request.request_id !== "string" || !request.request_id) {
      throw new Error("request_id_missing");
    }
    let sending = false;
    try {
      if (request.type === "send") {
        if (request.route?.kind !== "weixin" || typeof request.route.target !== "string" ||
            !request.route.target.trim() || typeof request.text !== "string" || !request.text.trim()) {
          throw new Error("invalid_send");
        }
        sending = true;
        const receipt = await this.sdk.send(request.route.target, request.text, request.timeout_ms);
        if (!receipt?.messageId) throw new Error("send_receipt_missing");
        this.emit({type: "ack", request_id: request.request_id, status: "sent"});
        return;
      }
      if (request.type === "start_receiving") this.start();
      else if (request.type === "stop_receiving") await this.stop();
      else throw new Error("unknown_command");
      this.emit({type: "ack", request_id: request.request_id, status: "accepted"});
    } catch (error) {
      this.emit({type: "error", request_id: request.request_id,
        code: sending ? "weixin_send_failed" : "weixin_command_failed", uncertain: sending,
        exception_type: error.name});
    }
  }

  start() {
    if (this.receiver) throw new Error("already_receiving");
    this.controller = new AbortController();
    this.receiver = this.poll(this.controller.signal).catch((error) => {
      this.emit({type: "receiver_error", code: "weixin_receiver_failed", exception_type: error.name});
    });
  }

  async poll(signal) {
    let cursor = this.sdk.loadCursor();
    while (!signal.aborted) {
      const response = await this.sdk.poll(cursor, signal);
      if (signal.aborted) return;
      if ((response.ret !== undefined && response.ret !== 0) ||
          (response.errcode !== undefined && response.errcode !== 0)) {
        throw new Error("weixin_poll_rejected");
      }
      for (const raw of response.msgs ?? []) {
        const message = this.sdk.normalize(raw);
        if (!message) continue; // Non-text/system messages aren't Agent input.
        if (signal.aborted) return;
        await new Promise((resolve, reject) => {
          const abort = () => {
            this.pending.delete(message.message_id);
            resolve();
          };
          signal.addEventListener("abort", abort, {once: true});
          const finish = (fn) => () => {
            signal.removeEventListener("abort", abort);
            fn();
          };
          this.pending.set(message.message_id, {
            resolve: finish(resolve),
            reject: finish(() => reject(new Error("manager_enqueue_rejected"))),
          });
          this.emit({type: "message", ...message});
        });
        if (signal.aborted) return;
      }
      if (typeof response.get_updates_buf === "string" && response.get_updates_buf) {
        this.sdk.saveCursor(response.get_updates_buf);
        cursor = response.get_updates_buf;
      }
    }
  }

  async stop() {
    if (!this.receiver) return;
    this.controller.abort();
    await this.receiver;
    this.receiver = null;
    this.controller = null;
    this.pending.clear();
  }
}
