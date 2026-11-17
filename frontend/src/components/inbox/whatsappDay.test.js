import { describe, expect, test } from "vitest";
import { formatWhatsAppDay } from "./ChannelChat";

const daysAgo = (n) => new Date(Date.now() - n * 86400000).toISOString();

// Sampled from a real WhatsApp Web screenshot: "Yesterday", then a plain dd/mm/yyyy.
describe("WhatsApp day divider", () => {
  test("today and yesterday are words", () => {
    expect(formatWhatsAppDay(daysAgo(0), "en")).toBe("Today");
    expect(formatWhatsAppDay(daysAgo(1), "en")).toBe("Yesterday");
  });
  test("within the last week it is a weekday name", () => {
    expect(formatWhatsAppDay(daysAgo(3), "en")).toMatch(/^(Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day$/);
  });
  test("older than a week it is dd/mm/yyyy", () => {
    expect(formatWhatsAppDay("2026-11-01T10:00:00", "en")).toBe("01/11/2026");
  });
});
