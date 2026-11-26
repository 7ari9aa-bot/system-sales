/**
 * The "close my account" card, in each of the four states the server can answer with.
 *
 * The point of these assertions: the card must never offer a form it knows will be refused, and it
 * must never hide WHY it is not offering one. A sole owner sees the shop they have to hand over; a
 * person with an open request sees the request and the way to withdraw it.
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { I18nProvider } from "@/lib/i18n";
import AccountClosureCard from "./AccountClosureCard";

const render = (props) =>
  renderToStaticMarkup(
    <I18nProvider>
      <AccountClosureCard {...props} />
    </I18nProvider>
  );

const free = { request: null, blockers: [], memberships: 2 };

describe("AccountClosureCard", () => {
  test("an unread state renders the loading line, never a form", () => {
    const html = render({ state: null });
    expect(html).toContain('data-testid="closure-loading"');
    expect(html).not.toContain('data-testid="closure-form"');
  });

  test("a sole owner is told which shop blocks the request", () => {
    const html = render({
      state: {
        request: null,
        memberships: 1,
        blockers: [{ tenant_id: "t1", tenant_name: "Adel Electronics", role_code: "owner" }],
      },
    });
    expect(html).toContain('data-testid="closure-blocked"');
    expect(html).toContain("Adel Electronics");
    expect(html).not.toContain('data-testid="closure-form"');
    expect(html).not.toContain('data-testid="closure-submit"');
  });

  test("an open request is shown with the way to withdraw it", () => {
    const html = render({
      state: {
        ...free,
        request: {
          id: "r1",
          mode: "delete",
          status: "pending",
          reason: null,
          created_at: "2026-11-26T09:00:00+00:00",
        },
      },
    });
    expect(html).toContain('data-testid="closure-pending"');
    expect(html).toContain('data-testid="closure-withdraw"');
    expect(html).toContain("2026-11-26");
    expect(html).not.toContain('data-testid="closure-form"');
  });

  test("a decided request is history, not an open one", () => {
    const html = render({
      state: {
        ...free,
        request: {
          id: "r1",
          mode: "close",
          status: "cancelled",
          reason: null,
          created_at: "2026-11-26T09:00:00+00:00",
        },
      },
    });
    expect(html).toContain('data-testid="closure-decided"');
    expect(html).toContain('data-testid="closure-form"');
  });

  test("with nothing in the way the form offers both choices and the impact of each", () => {
    const html = render({ state: free });
    expect(html).toContain('data-testid="closure-form"');
    expect(html).toContain('value="close"');
    expect(html).toContain('value="delete"');
    expect(html).toContain('data-testid="closure-submit"');
    expect(html).toContain("Member of 2 store(s)");
  });

  test("an error from the server is spoken, and the form is still not claimed as done", () => {
    const html = render({ state: free, error: "The request was not recorded. Try again." });
    expect(html).toContain('role="alert"');
    expect(html).toContain("The request was not recorded");
  });
});
