/**
 * Assert that a global-search hit routes to the record it names (gap F7).
 *
 * `docs/GAP_REGISTER.md:443`: "Global search drops entity_id for 4/5 types;
 * `?conversation=` ignored by inbox → Cmd+K is a dead end." Two corrections the
 * code forces: the inbox reads `?conversation=` today (`src/app/(dash)/inbox/
 * page.tsx:325-330`), and the SearchPort returns `customer` and `product` only
 * (`backend/app/core/search.py:72`), so three of the five branches in
 * `searchHref` are defensive rather than live.
 *
 * What IS genuinely broken is narrower and worse than "4 of 5":
 *
 *   1. `order` has a detail route at `src/app/(dash)/orders/[id]/page.tsx` and
 *      the palette throws the id away anyway, sending the user to the bare list.
 *   2. `searchHref` was private to the component, so nothing could check where a
 *      hit opens — including this file.
 *   3. A missing or empty `entity_id` interpolated into a path produces
 *      `/customers/undefined`, which is an error page, not a dead end's answer.
 *   4. `active` indexes a list a later response is allowed to shorten. Hover the
 *      last row, receive a shorter result set, press Enter: nothing happens.
 *
 * The route table is read off disk, not hardcoded: the day someone adds
 * `/products/[id]/page.tsx` this gate starts demanding the product id survive
 * too. A gate that encodes today's limitations as expected behavior is
 * documentation, not a test.
 *
 * Run: node scripts/check-search-hits.mjs
 */

import { readdir } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { createReact, findByTestId } from "./lib/hook-harness.mjs";
import { createGate, fakeResponse } from "./lib/browser-chain.mjs";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const src = (p) => join(ROOT, "src", p);
const DASH = join(ROOT, "src", "app", "(dash)");

const CHAIN = [
  src("lib/queries.ts"),
  src("lib/api.ts"),
  src("lib/auth-api.ts"),
  src("lib/t.ts"),
  src("lib/i18n.tsx"),
  src("lib/utils.ts"),
];

const ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";

const problems = [];
function check(label, actual, expected) {
  if (!Object.is(actual, expected)) {
    problems.push(`${label}\n    expected ${expected}\n    actual   ${actual}`);
  }
}

/** Which dashboard segment holds a hit's record. */
const ENTITY_SEGMENT = {
  customer: "customers",
  product: "products",
  order: "orders",
  task: "tasks",
};

/** Segments with a real `[id]/page.tsx` under `(dash)` right now. */
async function detailRoutes() {
  const found = new Set();
  let entries = [];
  try {
    entries = await readdir(DASH, { withFileTypes: true });
  } catch (err) {
    problems.push(`cannot read ${DASH} to learn which detail routes exist: ${err}`);
    return found;
  }
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    let inner = [];
    try {
      inner = await readdir(join(DASH, entry.name, "[id]"), { withFileTypes: true });
    } catch {
      continue; // no detail route for this segment
    }
    if (inner.some((i) => i.isFile() && /^page\.tsx?$/.test(i.name))) found.add(entry.name);
  }
  return found;
}

const routes = await detailRoutes();
console.log(`  · detail routes on disk under (dash): ${[...routes].sort().join(", ") || "(none)"}`);

async function openPalette(hits) {
  const runtime = createReact();
  const gate = await createGate({
    entry: src("components/command-palette.tsx"),
    chain: CHAIN,
    react: runtime,
    tokens: { access_token: "a", refresh_token: "b" },
    fetch: async () => fakeResponse({ status: 200, body: hits }),
  });
  // The gate's react-query stub binds mutate once per observer (v5.103);
  // flipping unstableMutate lets the stub run the mutation through the mocked
  // fetch. Without this the search data never arrives and the rows the
  // section below needs never render.
  globalThis.__gate.unstableMutate = true;

  gate.mount((props) => gate.module.CommandPalette(props), { open: true, onOpenChange: () => {} });
  if (gate.problems.length) throw new Error(`chain did not resolve: ${gate.problems.join("; ")}`);
  return { gate, runtime };
}

/** Finds the CommandRow ELEMENT for a search item.
 *
 *  The gate's tree does not expand child components, so a row is the
 *  CommandRow element itself — its `props.item.id` names the hit and its
 *  `props.onRun` is the handler the click forwards to. A DOM `data-testid`
 *  for the row never materializes in this tree; that is a property of the
 *  harness, not of the app. */
function findItemRow(root, itemId) {
  const stack = [root];
  while (stack.length) {
    const node = stack.pop();
    if (!node || typeof node !== "object") continue;
    if (node.props?.item?.id === itemId) return node;
    for (const c of [node.children, node.props?.children].flat(Infinity)) {
      if (c && typeof c === "object") stack.push(c);
    }
  }
  return null;
}

async function typeInto(gate, runtime, value) {
  const input = findByTestId(gate.instance.tree, "command-input");
  if (!input) throw new Error('nothing rendered with data-testid="command-input"');
  input.props.onChange({ target: { value } });
  gate.instance.dirty = true;
  runtime.pump();
  runtime.advance(260);
  await gate.flush();
  runtime.advance(260);
  await gate.flush();
}

/* ------------------------------------- 1. where each entity type opens ----- */

const searchHref = await (async () => {
  const { gate } = await openPalette([]);
  const fn = gate.module.searchHref;
  await gate.cleanup();
  if (typeof fn !== "function") {
    problems.push(
      "searchHref is not exported from command-palette.tsx — where a hit opens cannot be " +
        "checked by anything, so a dropped entity_id is invisible to every tool in the repo",
    );
    return null;
  }
  return fn;
})();

if (searchHref) {
  check(
    "a conversation hit opens the inbox on that conversation",
    searchHref("conversation", ID),
    `/inbox?conversation=${ID}`,
  );
  for (const [entityType, segment] of Object.entries(ENTITY_SEGMENT)) {
    const href = String(searchHref(entityType, ID));
    if (routes.has(segment)) {
      check(
        `a "${entityType}" hit opens its own record (${segment}/[id] exists on disk)`,
        href,
        `/${segment}/${ID}`,
      );
    } else {
      check(
        `an "${entityType}" hit with no detail route stays on its own list`,
        href.startsWith(`/${segment}`),
        true,
      );
    }
  }
  check(
    "an id is percent-encoded, never interpolated raw",
    String(searchHref("customer", "../../etc/passwd")).includes("%2F"),
    true,
  );
  for (const bad of ["", undefined, null]) {
    const href = String(searchHref("customer", bad));
    check(`an empty id (${JSON.stringify(bad)}) never reaches the URL`, /undefined|null|\/$/.test(href), false);
  }
  check("an unrecognized type is still a path inside the app", String(searchHref("widget", ID)).startsWith("/"), true);
}

/* --------------------- 2. clicking a hit navigates to that hit's record ---- */
//
// `searchHref` is the rule; this is the same failure measured where a user
// feels it — the row that renders for an order hit, clicked, must put the
// order's id in the URL. Today it calls `router.push("/orders")`.

{
  const CUSTOMER = "11111111-1111-4111-8111-111111111111";
  const ORDER = "22222222-2222-4222-8222-222222222222";
  const hits = [
    { entity_type: "customer", entity_id: CUSTOMER, title: "عميل", snippet: null },
    { entity_type: "order", entity_id: ORDER, title: "طلب", snippet: null },
  ];

  const { gate, runtime } = await openPalette(hits);
  await typeInto(gate, runtime, "عميل");

  const list = findByTestId(gate.instance.tree, "command-list");
  for (const [entityType, id, want] of [
    ["customer", CUSTOMER, `/customers/${CUSTOMER}`],
    ["order", ORDER, `/orders/${ORDER}`],
  ]) {
    gate.navigations().length = 0;
    const row = findItemRow(list, `search-${entityType}-${id}`);
    if (!row) {
      problems.push(`no row rendered for the ${entityType} hit, so clicking it went untested`);
      continue;
    }
    row.props.onRun?.();
    const nav = gate.navigations().at(-1);
    check(`clicking the ${entityType} hit opens its record`, nav?.href, want);
  }
  await gate.cleanup();
}

if (problems.length) {
  console.error("✗ src/components/command-palette.tsx — where a search hit opens (F7)\n");
  for (const problem of problems) console.error(`  - ${problem}`);
  console.error("");
  process.exit(1);
}

console.log("✓ src/components/command-palette.tsx: a search hit opens the record it names (F7)");
