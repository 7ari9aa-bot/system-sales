import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const setActiveChannel = vi.fn();
let data = { lang: "en", canAct: true, unreadMessages: 3, unanswered: 0, pageName: "Fihrist", pageAvatar: "", live: {}, pageError: null };
vi.mock("./useFacebookData", () => ({ useFacebookData: () => data }));
vi.mock("@/pages/inbox/InboxProvider", () => ({
  InboxProvider: ({ children }) => children,
  useInbox: () => ({ channels: [], unreadByChannel: {}, setActiveChannel, activeChannel: "facebook", t: (k) => k }),
}));
vi.mock("@/components/inbox/ChannelSwitcher", () => ({ default: () => null }));
vi.mock("@/components/facebook/FacebookNewPostDialog", () => ({ default: () => null }));
import FacebookLayout from "./FacebookLayout";

const html = (path = "/facebook/posts") => renderToStaticMarkup(<MemoryRouter initialEntries={[path]}><FacebookLayout /></MemoryRouter>);

describe("Messenger on the Facebook screen", () => {
  it("is no longer a tab in the main navigation", () => {
    const nav = html().match(/<nav[\s\S]*?<\/nav>/)[0];
    expect(nav).not.toContain("/facebook/messages");
    expect(nav).not.toMatch(/aria-label="Messages"/);
  });
  it("is a small Messenger button next to the Page name that opens the Messenger channel", () => {
    const out = html();
    const btn = out.match(/<button[^>]*data-testid="fb-messenger-link"[^>]*>/);
    expect(btn, "Messenger button beside the Page name").not.toBeNull();
    expect(btn[0]).toContain('aria-label="Messenger"');
  });
  it("keeps the unread count on that button", () => {
    const btn = html().match(/<button[^>]*data-testid="fb-messenger-link"[\s\S]*?<\/button>/)[0];
    expect(btn).toMatch(/>3<\/span>/);
  });
});
