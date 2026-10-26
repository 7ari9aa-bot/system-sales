import { describe, expect, it, vi } from "vitest";
import { createIntentKeys, fingerprint } from "./intentKeys";
import { appendLocalMessage, sendReply, TIMEOUT_MESSAGE } from "./inboxSend";

const fresh = () => createIntentKeys("msg");
const err = (props) => Object.assign(new Error(props.message ?? "boom"), props);

describe("createIntentKeys", () => {
  it("returns the same key for the same content and slot", () => {
    const k = fresh();
    expect(k.take("a", { text: "hi" })).toBe(k.take("a", { text: "hi" }));
  });

  it("returns a new key when the content changes", () => {
    const k = fresh();
    expect(k.take("a", { text: "hi" })).not.toBe(k.take("a", { text: "hi!" }));
  });

  it("keeps slots independent", () => {
    const k = fresh();
    expect(k.take("a", { text: "hi" })).not.toBe(k.take("b", { text: "hi" }));
  });

  it("forgets a slot after done()", () => {
    const k = fresh();
    const first = k.take("a", { text: "hi" });
    k.done("a");
    expect(k.size()).toBe(0);
    expect(k.take("a", { text: "hi" })).not.toBe(first);
  });

  it("fingerprint ignores object key order", () => {
    expect(fingerprint({ a: 1, b: [1, { c: 2, d: 3 }] })).toBe(fingerprint({ b: [1, { d: 3, c: 2 }], a: 1 }));
  });

  it("generates keys long enough for the server and unique", () => {
    const k = fresh();
    const keys = new Set(Array.from({ length: 50 }, (_, i) => k.take(`s${i}`, i)));
    expect(keys.size).toBe(50);
    for (const key of keys) expect(key.length).toBeGreaterThanOrEqual(8);
  });
});

describe("sendReply", () => {
  it("posts the text with an Idempotency-Key header", async () => {
    const api = vi.fn(async () => ({ id: "m1", status: "queued" }));
    const out = await sendReply("c1", "hello", { api, intents: fresh() });
    expect(out).toEqual({ ok: true, sent: { id: "m1", status: "queued" } });
    const [path, init] = api.mock.calls[0];
    expect(path).toBe("/conversations/c1/messages");
    expect(init.method).toBe("POST");
    expect(init.body).toEqual({ body: "hello" });
    expect(init.headers["Idempotency-Key"]).toMatch(/^msg-/);
  });

  it("a retry after a TIMEOUT re-sends the SAME key (cannot duplicate)", async () => {
    const intents = fresh();
    const api = vi.fn()
      .mockRejectedValueOnce(err({ code: "timeout", status: 0, message: "slow" }))
      .mockResolvedValueOnce({ id: "m1", status: "queued" });
    const first = await sendReply("c1", "hello", { api, intents });
    const second = await sendReply("c1", "hello", { api, intents });
    expect(first).toEqual({ ok: false, error: TIMEOUT_MESSAGE });
    expect(second.ok).toBe(true);
    expect(api.mock.calls[1][1].headers["Idempotency-Key"])
      .toBe(api.mock.calls[0][1].headers["Idempotency-Key"]);
  });

  it("a retry after a network failure keeps the key too", async () => {
    const intents = fresh();
    const api = vi.fn()
      .mockRejectedValueOnce(err({ code: "network", status: 0 }))
      .mockResolvedValueOnce({ id: "m1" });
    await sendReply("c1", "hello", { api, intents });
    await sendReply("c1", "hello", { api, intents });
    expect(api.mock.calls[1][1].headers["Idempotency-Key"])
      .toBe(api.mock.calls[0][1].headers["Idempotency-Key"]);
  });

  it("a 5xx burns the server key, so the next attempt gets a NEW one (not a stuck 409)", async () => {
    const intents = fresh();
    const api = vi.fn()
      .mockRejectedValueOnce(err({ status: 503, message: "down" }))
      .mockResolvedValueOnce({ id: "m1" });
    const first = await sendReply("c1", "hello", { api, intents });
    await sendReply("c1", "hello", { api, intents });
    expect(first).toEqual({ ok: false, error: "down" });
    expect(api.mock.calls[1][1].headers["Idempotency-Key"])
      .not.toBe(api.mock.calls[0][1].headers["Idempotency-Key"]);
  });

  it("a 4xx rejection keeps the key (server released it) so a fix can reuse it", async () => {
    const intents = fresh();
    const api = vi.fn()
      .mockRejectedValueOnce(err({ status: 409, message: "conversation is closed" }))
      .mockResolvedValueOnce({ id: "m1" });
    const first = await sendReply("c1", "hello", { api, intents });
    await sendReply("c1", "hello", { api, intents });
    expect(first.error).toBe("conversation is closed");
    expect(api.mock.calls[1][1].headers["Idempotency-Key"])
      .toBe(api.mock.calls[0][1].headers["Idempotency-Key"]);
  });

  it("edited text after a failure is a new intention with a new key", async () => {
    const intents = fresh();
    const api = vi.fn()
      .mockRejectedValueOnce(err({ code: "timeout", status: 0 }))
      .mockResolvedValueOnce({ id: "m1" });
    await sendReply("c1", "hello", { api, intents });
    await sendReply("c1", "hello there", { api, intents });
    expect(api.mock.calls[1][1].headers["Idempotency-Key"])
      .not.toBe(api.mock.calls[0][1].headers["Idempotency-Key"]);
  });

  it("after a success, sending the same text again is a deliberate new message (new key)", async () => {
    const intents = fresh();
    const api = vi.fn(async () => ({ id: "m" }));
    await sendReply("c1", "ok", { api, intents });
    await sendReply("c1", "ok", { api, intents });
    expect(api.mock.calls[1][1].headers["Idempotency-Key"])
      .not.toBe(api.mock.calls[0][1].headers["Idempotency-Key"]);
  });

  it("different conversations never share a key", async () => {
    const intents = fresh();
    const api = vi.fn(async () => ({ id: "m" }));
    await sendReply("c1", "ok", { api, intents });
    await sendReply("c2", "ok", { api, intents });
    expect(api.mock.calls[1][1].headers["Idempotency-Key"])
      .not.toBe(api.mock.calls[0][1].headers["Idempotency-Key"]);
  });

  it("falls back to a generic message when the error has none", async () => {
    const api = vi.fn().mockRejectedValue({});
    const out = await sendReply("c1", "x", { api, intents: fresh() });
    expect(out).toEqual({ ok: false, error: "Could not send the message." });
  });
});

describe("appendLocalMessage (channel switch during send)", () => {
  const msg = { id: "m1", text: "hi" };
  const base = () => ({
    whatsapp: [{ id: "c1", messages: [], preview: "" }, { id: "c2", messages: [{ id: "x" }] }],
    telegram: [{ id: "c1", messages: [], preview: "" }],
  });

  it("adds the echo to the channel it was sent from, even if another is active now", () => {
    // the user sent from whatsapp, then switched to telegram before the reply came back
    const next = appendLocalMessage(base(), "whatsapp", "c1", msg, "hi");
    expect(next.whatsapp[0].messages).toEqual([msg]);
    expect(next.whatsapp[0].preview).toBe("hi");
    expect(next.telegram[0].messages).toEqual([]); // the old bug put it here
  });

  it("leaves other conversations in the channel untouched", () => {
    const next = appendLocalMessage(base(), "whatsapp", "c1", msg, "hi");
    expect(next.whatsapp[1].messages).toEqual([{ id: "x" }]);
  });

  it("does not mutate the previous state", () => {
    const before = base();
    appendLocalMessage(before, "whatsapp", "c1", msg, "hi");
    expect(before.whatsapp[0].messages).toEqual([]);
  });

  it("tolerates a channel with no loaded conversations", () => {
    expect(appendLocalMessage({}, "facebook", "c1", msg, "hi")).toEqual({ facebook: [] });
  });
});
