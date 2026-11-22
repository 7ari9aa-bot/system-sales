import { describe, it, expect } from "vitest";
import {
  MESSENGER_BUBBLE_RADIUS,
  MESSENGER_JOIN_RADIUS,
  messengerBubbleBackground,
  messengerBubbleCorners,
  messengerGroup,
  messengerPresence,
  messengerSeen,
  messengerSeenMessageId,
} from "./messengerChat";

const at = (minutes, extra = {}) => ({
  id: `m${minutes}`,
  side: "out",
  createdAt: new Date(Date.UTC(2026, 10, 22, 10, minutes)).toISOString(),
  ...extra,
});

describe("messengerGroup", () => {
  it("joins two own messages sent within the gap and squares only the touching corners", () => {
    const list = [at(0), at(1), at(1, { side: "in", id: "in1" })];
    const first = messengerGroup(list, 0);
    const second = messengerGroup(list, 1);
    expect(first).toMatchObject({ first: true, last: false, size: 2 });
    expect(second).toMatchObject({ first: false, last: true, size: 2 });
    expect(messengerBubbleCorners({ out: true, ...first })).toBe("rounded-ee-[4px]");
    expect(messengerBubbleCorners({ out: true, ...second })).toBe("rounded-se-[4px]");
  });

  it("never joins a message across the 3 minute gap", () => {
    const list = [at(0), at(5)];
    expect(messengerGroup(list, 1)).toMatchObject({ first: true, last: true, alone: true });
  });

  it("never joins across sides or around a system message", () => {
    const list = [at(0), at(1, { side: "in" })];
    expect(messengerGroup(list, 1)).toMatchObject({ alone: true });
    const withSystem = [at(0), at(1, { senderType: "system" }), at(2)];
    expect(messengerGroup(withSystem, 2)).toMatchObject({ first: true });
  });

  it("treats a missing timestamp as its own group", () => {
    const list = [{ id: "a", side: "out" }, { id: "b", side: "out" }];
    expect(messengerGroup(list, 1)).toMatchObject({ alone: true });
  });
});

describe("messengerBubbleCorners", () => {
  it("squares the inline-start corners for a received group", () => {
    expect(messengerBubbleCorners({ out: false, first: true, last: false })).toBe("rounded-es-[4px]");
    expect(messengerBubbleCorners({ out: false, first: false, last: true })).toBe("rounded-ss-[4px]");
  });

  it("draws a lone bubble with no squared corner", () => {
    expect(messengerBubbleCorners({ out: true, first: true, last: true })).toBe("");
  });

  it("keeps Messenger's 18px bubble and 4px join", () => {
    expect(MESSENGER_BUBBLE_RADIUS).toBe(18);
    expect(MESSENGER_JOIN_RADIUS).toBe(4);
  });
});

describe("messengerBubbleBackground", () => {
  const theme = { accent: "#0084FF", gradient: ["#00B2FF", "#006AFF"], in: "#F0F0F0" };

  it("paints an outgoing bubble with the theme gradient", () => {
    expect(messengerBubbleBackground(theme, true)).toBe("linear-gradient(135deg, #00B2FF, #006AFF)");
  });

  it("paints an incoming bubble flat grey", () => {
    expect(messengerBubbleBackground(theme, false)).toBe("#F0F0F0");
  });

  it("falls back to the accent when a theme carries no gradient", () => {
    expect(messengerBubbleBackground({ accent: "#8B5CF6" }, true)).toBe("#8B5CF6");
    expect(messengerBubbleBackground(null, true)).toBe("#0084FF");
  });
});

describe("messengerSeen", () => {
  it("only counts read, because Messenger draws no delivered tick", () => {
    expect(messengerSeen("read")).toBe(true);
    expect(messengerSeen("delivered")).toBe(false);
    expect(messengerSeen("sent")).toBe(false);
  });

  it("marks the newest own message that was read", () => {
    const list = [
      { id: "a", side: "out", status: "read" },
      { id: "b", side: "out", status: "sent" },
      { id: "c", side: "in", status: "read" },
    ];
    expect(messengerSeenMessageId(list)).toBeNull();
    expect(messengerSeenMessageId([...list.slice(0, 2), { id: "d", side: "out", status: "read" }])).toBe("d");
  });
});

describe("messengerPresence", () => {
  const now = Date.UTC(2026, 10, 22, 12, 0);

  it("says active now only inside the window", () => {
    expect(messengerPresence(new Date(now - 60_000).toISOString(), now)).toBe("activeNow");
    expect(messengerPresence(new Date(now - 10 * 60_000).toISOString(), now)).toBeNull();
    expect(messengerPresence(null, now)).toBeNull();
  });
});
