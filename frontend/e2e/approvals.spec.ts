import { expect, test } from "@playwright/test";
import { json, mockShell, seedAuth, seedLang, serverError, SHELL_ME } from "./support";

/* W5 exit gate — approvals (rendered by the "My Work" page).
 *
 * `useApprovals` parks HIGH-risk tool calls; the page shows them next to the
 * SLA-risk queue and the current user's assigned tasks. The risk level is
 * rendered through the i18n dictionary, so this spec pins the language to
 * English and asserts the label the app itself produces. */

const APPROVALS = {
  items: [
    {
      id: "ap1",
      status: "PENDING",
      action: "issue_refund",
      risk_level: "HIGH",
      entity_type: "order",
      entity_id: "o1",
      conversation_id: null,
      run_id: null,
      payload: {},
      requested_by: "user-1",
      expires_at: "2026-09-21T10:00:00Z",
      decided_at: null,
      consumed_at: null,
      rejection_reason: null,
      created_at: "2026-09-20T10:00:00Z",
    },
  ],
};

const SLA = {
  items: [
    {
      id: "s1",
      conversation_id: "c1",
      kind: "first_response",
      status: "at_risk",
      deadline_at: "2026-09-20T11:00:00Z",
      minutes_remaining: 12,
      at_risk: true,
    },
  ],
  timezone: "UTC",
};

const TASKS = [
  {
    id: "t1",
    title: "Call the courier",
    status: "todo",
    priority: 2,
    assignee_user_id: SHELL_ME.id,
    due_date: null,
    source: "manual",
  },
];

test.beforeEach(async ({ page }) => {
  await seedAuth(page);
  await seedLang(page, "en");
  await mockShell(page, SHELL_ME);
  await page.route("**/api/v1/sla/risk", (route) => json(route, SLA));
  await page.route("**/api/v1/tasks**", (route) => json(route, TASKS));
  await page.route("**/api/v1/conversations**", (route) =>
    json(route, { items: [], next_cursor: null }),
  );
  // my-work also lists the user's saved views (§97) — keep it mocked so only
  // the section under test can surface an error-state.
  await page.route("**/api/v1/platform/saved-views**", (route) => json(route, { items: [] }));
});

test("my-work surfaces pending approvals, their risk level, and assigned work", async ({ page }) => {
  await page.route("**/api/v1/ai/approvals**", (route) => json(route, APPROVALS));

  await page.goto("/my-work");

  await expect(page.getByText("issue_refund")).toBeVisible();
  await expect(page.getByText(/Risk level:\s*High/)).toBeVisible();
  await expect(page.getByText("Call the courier")).toBeVisible();
  // The SLA row links straight to the conversation it is timing.
  await expect(page.locator('a[href="/inbox?conversation=c1"]')).toBeVisible();
});

test("a failed approvals request renders a retryable alert in its section", async ({ page }) => {
  await page.route("**/api/v1/ai/approvals**", (route) =>
    serverError(route, "approvals unavailable"),
  );

  await page.goto("/my-work");

  const alert = page.getByTestId("error-state");
  await expect(alert).toBeVisible();
  await expect(alert).toContainText("approvals unavailable");
  await expect(alert.getByRole("button")).toBeVisible();
});
