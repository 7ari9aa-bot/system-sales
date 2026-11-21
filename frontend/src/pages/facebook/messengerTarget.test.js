import { describe, expect, it } from "vitest";
import { messengerTarget } from "./messengerTarget";

describe("where the Messenger button beside the Page name goes", () => {
  it("opens the Messenger channel when it is connected", () => {
    expect(messengerTarget([{ id: "messenger", connected: true }])).toEqual({ kind: "channel", id: "messenger" });
  });
  it("goes to channel settings when Messenger is not connected, instead of bouncing back to Facebook", () => {
    expect(messengerTarget([{ id: "messenger", connected: false }, { id: "facebook", connected: true }])).toEqual({ kind: "settings", path: "/settings/channels" });
  });
  it("goes to channel settings when the channel list has no Messenger row at all", () => {
    expect(messengerTarget([])).toEqual({ kind: "settings", path: "/settings/channels" });
    expect(messengerTarget(undefined)).toEqual({ kind: "settings", path: "/settings/channels" });
  });
});
