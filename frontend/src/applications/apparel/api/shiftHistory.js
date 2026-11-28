/**
 * The day log, read in full and cheaply.
 *
 * `GET /pos/sessions` returns one page (newest first). Reading only the first page silently hid
 * every older day, so the log is walked page by page with `offset` until a short page ends it.
 * A day's report is a separate request, so only the most recent REPORT_DAYS days fetch one:
 * opening the log costs a fixed number of requests, not one per day of history. An older day keeps
 * the figures the session itself stores (its closing balance) and shows the rest as unknown.
 */
export const PAGE_SIZE = 50;
export const MAX_PAGES = 40; // 2,000 days: a safety cap, not a limit anyone should reach
export const REPORT_DAYS = 30;

/** `list(query)` is `posApi.listSessions`. A failed page throws: a short history must not look complete. */
export async function loadAllSessions(list, { pageSize = PAGE_SIZE, maxPages = MAX_PAGES } = {}) {
  const out = [];
  for (let page = 0; page < maxPages; page += 1) {
    const rows = (await list(`limit=${pageSize}&offset=${page * pageSize}`)) ?? [];
    out.push(...rows);
    if (rows.length < pageSize) break;
  }
  return out;
}
