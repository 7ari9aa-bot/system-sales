import { describe, expect, it } from "vitest";
import { channelFromSearch } from "./channelFromSearch";

describe("?channel= on /inbox", () => {
  it("opens a known channel", () => {
    expect(channelFromSearch("?channel=messenger")).toBe("messenger");
    expect(channelFromSearch("?x=1&channel=telegram")).toBe("telegram");
  });
  it("ignores unknown or missing channels, so a bad link cannot break the inbox", () => {
    expect(channelFromSearch("?channel=nope")).toBeNull();
    expect(channelFromSearch("")).toBeNull();
    expect(channelFromSearch(undefined)).toBeNull();
  });
});

import { inboxPathFor } from "./channelFromSearch";
describe("leaving a channel page for the inbox", () => {
  it("carries the chosen channel in the link", () => {
    expect(inboxPathFor("messenger")).toBe("/inbox?channel=messenger");
    expect(inboxPathFor("telegram")).toBe("/inbox?channel=telegram");
  });
});
