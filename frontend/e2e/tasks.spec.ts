import { expect, test } from "@playwright/test";
import { json, mockShell, seedAuth, serverError } from "./support";

/* W5 exit gate — tasks. */

const TASKS = [
  {
    id: "t1",
    title: "Follow up with Layla",
    status: "todo",
    priority: 2,
    assignee_user_id: "user-1",
    due_date: null,
    source: "manual",
  },
  {
    id: "t2",
    title: "Restock blue abaya",
    status: "done",
    priority: 1,
    assignee_user_id: "user-1",
    due_date: null,
    source: "manual",
  },
];

test.beforeEach(async ({ page }) => {
  await seedAuth(page);
  await mockShell(page);
  await page.route("**/api/v1/tasks**", (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() === "POST" && url.pathname.endsWith("/tasks")) {
      return json(route, { id: "t9", status: "todo" });
    }
    return json(route, TASKS);
  });
});

test("lists tasks and filters them by status", async ({ page }) => {
  await page.goto("/tasks");

  await expect(page.getByText("Follow up with Layla")).toBeVisible();
  await expect(page.getByText("Restock blue abaya")).toBeVisible();

  await page.getByTestId("task-filter-done").click();

  await expect(page.getByText("Restock blue abaya")).toBeVisible();
  await expect(page.getByText("Follow up with Layla")).toHaveCount(0);
});

test("marking a task done posts the status change", async ({ page }) => {
  await page.goto("/tasks");

  const posted = page.waitForRequest(
    (request) => request.url().endsWith("/api/v1/tasks/t1/status") && request.method() === "POST",
  );
  await page.getByTestId("task-done-t1").click();
  await posted;
});

test("creating a task from the ?new=1 deep link posts to the API", async ({ page }) => {
  await page.goto("/tasks?new=1");

  await expect(page.getByTestId("task-submit")).toBeVisible();
  await page.locator("#task-title").fill("Call the courier");

  const posted = page.waitForRequest(
    (request) => request.url().endsWith("/api/v1/tasks") && request.method() === "POST",
  );
  await page.getByTestId("task-submit").click();
  await posted;
});

test("an empty task list renders the empty state", async ({ page }) => {
  await page.route("**/api/v1/tasks**", (route) => json(route, []));

  await page.goto("/tasks");

  await expect(page.getByTestId("tasks-empty")).toBeVisible();
});

test("a failed tasks request renders a retryable alert", async ({ page }) => {
  await page.route("**/api/v1/tasks**", (route) => serverError(route, "tasks unavailable"));

  await page.goto("/tasks");

  const alert = page.getByTestId("error-state");
  await expect(alert).toBeVisible();
  await expect(alert).toContainText("tasks unavailable");
  await expect(alert.getByRole("button")).toBeVisible();
});
