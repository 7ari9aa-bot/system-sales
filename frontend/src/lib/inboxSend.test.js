import { describe, expect, it, vi } from "vitest";
import { createIntentKeys, fingerprint } from "./intentKeys";
import { appendLocalMessage, sendReply, setMyReaction, TIMEOUT_MESSAGE, uploadMedia } from "./inboxSend";

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

describe("sendReply quoting", () => {
  const okApi = () => vi.fn().mockResolvedValue({ id: "m1" });

  it("sends the quoted message id when replying", async () => {
    const api = okApi();
    await sendReply("c1", "تمام", { api, intents: fresh(), replyToId: "msg-9" });
    expect(api.mock.calls[0][1].body).toEqual({ body: "تمام", reply_to_message_id: "msg-9" });
  });

  it("leaves the body exactly as before when nothing is quoted", async () => {
    const api = okApi();
    await sendReply("c1", "تمام", { api, intents: fresh() });
    expect(api.mock.calls[0][1].body).toEqual({ body: "تمام" });
  });

  it("the same words in reply to a different message is a new send, not a replay", async () => {
    const api = okApi();
    const intents = fresh();
    // Both attempts end without success, so the slot keeps its key.
    api.mockRejectedValue(err({ code: "timeout" }));
    await sendReply("c1", "تمام", { api, intents, replyToId: "msg-1" });
    await sendReply("c1", "تمام", { api, intents, replyToId: "msg-2" });
    const keys = api.mock.calls.map((c) => c[1].headers["Idempotency-Key"]);
    expect(keys[0]).not.toBe(keys[1]);
  });

  it("a retry of the same quoted reply reuses its key", async () => {
    const api = vi.fn().mockRejectedValue(err({ code: "timeout" }));
    const intents = fresh();
    await sendReply("c1", "تمام", { api, intents, replyToId: "msg-1" });
    await sendReply("c1", "تمام", { api, intents, replyToId: "msg-1" });
    const keys = api.mock.calls.map((c) => c[1].headers["Idempotency-Key"]);
    expect(keys[0]).toBe(keys[1]);
  });
});

describe("sendReaction", () => {
  it("posts the emoji to the message's reaction route", async () => {
    const api = vi.fn().mockResolvedValue({});
    const { sendReaction } = await import("./inboxSend");
    const r = await sendReaction("c1", "m1", "👍", { api });
    expect(r).toEqual({ ok: true });
    expect(api).toHaveBeenCalledWith("/conversations/c1/messages/m1/reaction", { method: "POST", body: { emoji: "👍" } });
  });

  it("reports the server's reason when it is refused", async () => {
    const { sendReaction } = await import("./inboxSend");
    const api = vi.fn().mockRejectedValue(err({ message: "this message cannot be reacted to" }));
    expect(await sendReaction("c1", "m1", "👍", { api })).toEqual({ ok: false, error: "this message cannot be reacted to" });
  });
});

describe("setMyReaction", () => {
  const map = () => ({
    whatsapp: [
      { id: "c1", messages: [{ id: "m1", reactions: ["😂"], myReaction: "" }, { id: "m2", reactions: [] }] },
      { id: "c2", messages: [{ id: "m1", reactions: [] }] },
    ],
    instagram: [{ id: "c1", messages: [{ id: "m1", reactions: [] }] }],
  });

  it("adds our reaction next to the customer's", () => {
    const next = setMyReaction(map(), "whatsapp", "c1", "m1", "👍");
    expect(next.whatsapp[0].messages[0]).toMatchObject({ reactions: ["😂", "👍"], myReaction: "👍" });
  });

  it("changing it replaces ours and keeps theirs", () => {
    const once = setMyReaction(map(), "whatsapp", "c1", "m1", "👍");
    const twice = setMyReaction(once, "whatsapp", "c1", "m1", "❤️", "👍");
    expect(twice.whatsapp[0].messages[0].reactions).toEqual(["😂", "❤️"]);
  });

  it("withdrawing removes only ours", () => {
    const once = setMyReaction(map(), "whatsapp", "c1", "m1", "👍");
    const gone = setMyReaction(once, "whatsapp", "c1", "m1", "", "👍");
    expect(gone.whatsapp[0].messages[0]).toMatchObject({ reactions: ["😂"], myReaction: "" });
  });

  it("touches nothing else: other messages, conversations or channels", () => {
    const before = map();
    const next = setMyReaction(before, "whatsapp", "c1", "m1", "👍");
    expect(next.whatsapp[0].messages[1]).toBe(before.whatsapp[0].messages[1]);
    expect(next.whatsapp[1]).toBe(before.whatsapp[1]);
    expect(next.instagram).toBe(before.instagram);
  });

  it("putting back the previous value undoes a refused reaction", () => {
    const start = map();
    const tried = setMyReaction(start, "whatsapp", "c1", "m1", "👍");
    const undone = setMyReaction(tried, "whatsapp", "c1", "m1", "", "👍");
    expect(undone.whatsapp[0].messages[0].reactions).toEqual(["😂"]);
  });
});

describe("sending a file", () => {
  const MEDIA = "9b2f3c1e-0000-4000-8000-000000000001";

  it("posts the media id with the caption and no empty body", async () => {
    const api = vi.fn().mockResolvedValue({ id: "m1" });
    await sendReply("c1", "الفاتورة", { api, intents: fresh(), mediaId: MEDIA });
    expect(api.mock.calls[0][1].body).toEqual({ body: "الفاتورة", media_id: MEDIA });
  });

  it("sends a file with no caption without a body field", async () => {
    const api = vi.fn().mockResolvedValue({ id: "m1" });
    await sendReply("c1", "", { api, intents: fresh(), mediaId: MEDIA });
    expect(api.mock.calls[0][1].body).toEqual({ media_id: MEDIA });
  });

  it("a text-only send is unchanged", async () => {
    const api = vi.fn().mockResolvedValue({ id: "m1" });
    await sendReply("c1", "hi", { api, intents: fresh() });
    expect(api.mock.calls[0][1].body).toEqual({ body: "hi" });
  });

  it("a different file is a NEW intention, the same file is a replay", async () => {
    const intents = fresh();
    const api = vi.fn().mockRejectedValue(err({ code: "timeout" }));
    await sendReply("c1", "x", { api, intents, mediaId: "A" });
    await sendReply("c1", "x", { api, intents, mediaId: "A" });
    await sendReply("c1", "x", { api, intents, mediaId: "B" });
    const keys = api.mock.calls.map((c) => c[1].headers["Idempotency-Key"]);
    expect(keys[0]).toBe(keys[1]);
    expect(keys[2]).not.toBe(keys[0]);
  });
});

describe("uploadMedia", () => {
  const f = Object.assign(new Blob(["%PDF-"], { type: "application/pdf" }), { name: "فاتورة مايو.pdf" });

  it("sends the raw file with its type and an encoded name", async () => {
    const api = vi.fn().mockResolvedValue({ media_id: "m", kind: "document", filename: "x.pdf", size: 5 });
    const r = await uploadMedia("c1", f, { api });
    expect(r).toEqual({ ok: true, media: { media_id: "m", kind: "document", filename: "x.pdf", size: 5 } });
    const [path, opts] = api.mock.calls[0];
    expect(path).toBe("/conversations/c1/media");
    expect(opts).toMatchObject({ method: "POST", body: f, rawBody: true, contentType: "application/pdf" });
    expect(decodeURIComponent(opts.headers["X-Filename"])).toBe("فاتورة مايو.pdf");
    expect(opts.headers["X-As-Sticker"]).toBeUndefined();
  });

  it("marks a sticker", async () => {
    const api = vi.fn().mockResolvedValue({});
    await uploadMedia("c1", f, { api, asSticker: true });
    expect(api.mock.calls[0][1].headers["X-As-Sticker"]).toBe("true");
  });

  it("reports the server's reason", async () => {
    const api = vi.fn().mockRejectedValue(err({ message: "a image can be at most 5 MB on WhatsApp", status: 400 }));
    expect(await uploadMedia("c1", f, { api })).toEqual({ ok: false, error: "a image can be at most 5 MB on WhatsApp" });
  });

  it("says so on a timeout", async () => {
    const api = vi.fn().mockRejectedValue(err({ code: "timeout" }));
    expect((await uploadMedia("c1", f, { api })).error).toMatch(/too long/);
  });

  it("an abort is not an error to show", async () => {
    const api = vi.fn().mockRejectedValue(Object.assign(new Error("x"), { name: "AbortError" }));
    expect(await uploadMedia("c1", f, { api })).toMatchObject({ ok: false, aborted: true, error: "" });
  });
});

describe("sendReply with a heart", () => {
  it("posts heart:true and never the text, even when the screen passes the heart as text", async () => {
    const { sendReply } = await import("./inboxSend");
    const api = vi.fn().mockResolvedValue({ id: "m9", status: "queued" });
    const r = await sendReply("c1", "\u2764\ufe0f", { api, heart: true });
    expect(r.ok).toBe(true);
    expect(api).toHaveBeenCalledWith("/conversations/c1/messages", expect.objectContaining({ body: { heart: true } }));
  });

  it("a heart and a plain send are different intentions (different keys)", async () => {
    const { sendReply } = await import("./inboxSend");
    const keys = [];
    const api = vi.fn().mockImplementation(async (_p, o) => { keys.push(o.headers["Idempotency-Key"]); throw Object.assign(new Error("x"), { status: 400 }); });
    await sendReply("c2", "\u2764\ufe0f", { api, heart: true });
    await sendReply("c2", "\u2764\ufe0f", { api });
    expect(keys[0]).not.toBe(keys[1]);
  });
});
