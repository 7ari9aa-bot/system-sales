/**
 * Assert that one settled query in the command palette costs ONE `/search`
 * request, forever (gap F3).
 *
 * `docs/GAP_REGISTER.md:439` states: "Command palette fires `/search` in an
 * infinite loop (mutate identity in effect deps) (`command-palette.tsx:114-122`)".
 * Those line numbers no longer hold that code — the palette now destructures
 * `mutate`/`reset` off the mutation and lists those two in its effect's deps
 * instead of the mutation object — so the register line is a claim about HEAD
 * that has to be tested rather than repeated. Testing it needs something that
 * runs a component body the way React does, and this repo has no such thing:
 * Playwright cannot start here (it needs a dev server, and this machine cannot
 * bind a port), so every `e2e/*.spec.ts` is CI-only and would surface a request
 * loop only after it merged.
 *
 * This gate therefore mounts the SHIPPING `command-palette.tsx` — through the
 * real `queries.ts` and `api.ts`, against a stubbed `window.fetch` and a virtual
 * clock — types into the real input's `onChange`, and counts requests across a
 * horizon wide enough that a self-rearming effect cannot hide in it.
 *
 * The control section is the load-bearing half: it re-runs the same scenario
 * with the mutation's `mutate`/`reset` identity changed every render — the exact
 * mechanism the register names — and fails if the gate does NOT then see the
 * storm. A gate that passes because it cannot see the defect it guards is
 * defect O4 repeating.
 *
 * Run: node scripts/check-command-palette-search.mjs
 */

import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { createReact, findByTestId } from "./lib/hook-harness.mjs";
import { createGate, fakeResponse } from "./lib/browser-chain.mjs";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const src = (p) => join(ROOT, "src", p);

/** Everything under the palette that is logic stays the shipping module. */
const CHAIN = [
  src("lib/queries.ts"),
  src("lib/api.ts"),
  src("lib/auth-api.ts"),
  src("lib/t.ts"),
  src("lib/i18n.tsx"),
  src("lib/utils.ts"),
];

const HITS = [
  {
    entity_type: "customer",
    entity_id: "11111111-1111-4111-8111-111111111111",
    title: "عميل",
    snippet: null,
  },
];

/** How many debounce windows to walk. A loop is unbounded; over twelve windows
 *  "settles eventually" and "never stops" are trivially distinguishable. */
const HORIZON_ROUNDS = 12;
const DEBOUNCE_MS = 250;

const problems = [];
function check(label, actual, expected) {
  if (!Object.is(actual, expected)) {
    problems.push(`${label}\n    expected ${expected}\n    actual   ${actual}`);
  }
}

/** Runs a section, turning a render storm into a line of the report.
 *
 *  A self-rearming effect does not fail an assertion, it never stops rendering,
 *  so the harness raises `RenderStorm` instead of hanging. Reporting that as a
 *  plain finding is the whole point: an uncaught stack trace tells a reader
 *  nothing about which invariant broke. */
async function section(label, fn) {
  try {
    await fn();
  } catch (err) {
    if (err?.name === "RenderStorm") {
      problems.push(
        `${label}: ${err.message} — the palette never settled, so it re-requested ` +
          `until the harness stopped it`,
      );
    } else {
      problems.push(`${label}: threw ${err?.stack ?? err}`);
    }
  }
}

/** One palette, one fetch log, one virtual clock. */
async function openPalette({ unstableMutate = false } = {}) {
  const runtime = createReact();
  const gate = await createGate({
    entry: src("components/command-palette.tsx"),
    chain: CHAIN,
    react: runtime,
    tokens: { access_token: "a", refresh_token: "b" },
    fetch: async () => fakeResponse({ status: 200, body: HITS }),
  });

  // v5.103 binds `mutate`/`reset` once in MutationObserver's constructor, which
  // is what makes listing them in an effect's deps safe. `unstableMutate` turns
  // that guarantee off inside the gate's own react-query stub — the pre-fix
  // shape F3 describes. See the header of scripts/lib/browser-chain.mjs.
  globalThis.__gate.unstableMutate = unstableMutate;

  const palette = gate.module.CommandPalette;
  if (typeof palette !== "function") {
    await gate.cleanup();
    throw new Error("command-palette.tsx exports no CommandPalette");
  }
  gate.mount((props) => palette(props), { open: true, onOpenChange: () => {} });
  if (gate.problems.length) {
    throw new Error(`the gate could not resolve the chain: ${gate.problems.join("; ")}`);
  }
  return { gate, runtime };
}

/** Types through the real `onChange`, then walks `rounds` debounce windows. */
async function typeAndRun(gate, runtime, value, rounds = 1) {
  const input = findByTestId(gate.instance.tree, "command-input");
  if (!input) throw new Error('nothing rendered with data-testid="command-input"');
  input.props.onChange({ target: { value } });
  gate.instance.dirty = true;
  runtime.pump?.();
  await gate.flush();
  for (let i = 0; i < rounds; i++) {
    runtime.advance(DEBOUNCE_MS + 10);
    await gate.flush();
  }
  return gate.fetches("/search").length;
}

/* ------------------------------------- 1. one query, one request, forever -- */

await section("one settled query", async () => {
  const { gate, runtime } = await openPalette();
  try {
    const total = await typeAndRun(gate, runtime, "عميل", HORIZON_ROUNDS);
    check(`one settled query costs one /search across ${HORIZON_ROUNDS} debounce windows`, total, 1);
    const search = gate.fetches("/search")[0];
    check(
      "and it is the trimmed term, url-encoded, on the one base URL",
      search?.url,
      "/api/v1/search?q=%D8%B9%D9%85%D9%8A%D9%84&limit=8",
    );
    check("and no credential rides in the URL", /token=/.test(search?.url ?? ""), false);
    check("the palette settled without a render storm", gate.instance.renders < 60, true);
    check("nothing is left re-arming a timer", runtime.pendingTimers(), 0);
  } finally {
    await gate.cleanup();
  }
});

/* --------------------------------------------- 2. typing is debounced ------ */
//
// Six keystrokes inside one 250ms window are one request, not six. An
// un-debounced palette puts a full-text query at the API per character, which
// is the same class of failure measured a different way.

await section("debounced typing", async () => {
  const { gate, runtime } = await openPalette();
  try {
    const input = findByTestId(gate.instance.tree, "command-input");
    let text = "";
    for (const ch of "customer") {
      text += ch;
      input.props.onChange({ target: { value: text } });
      gate.instance.dirty = true;
      runtime.pump();
      runtime.advance(40);
      await gate.flush();
    }
    check("six keystrokes 40ms apart fire nothing yet", gate.fetches("/search").length, 0);
    runtime.advance(DEBOUNCE_MS + 50);
    await gate.flush();
    check("and exactly one request once the window closes", gate.fetches("/search").length, 1);
  } finally {
    await gate.cleanup();
  }
});

/* ------------------------------------ 3. a short query cancels, not fires -- */

await section("a one-character query", async () => {
  const { gate, runtime } = await openPalette();
  try {
    check("one character never reaches the API", await typeAndRun(gate, runtime, "a", 4), 0);
  } finally {
    await gate.cleanup();
  }
});

/* ------------------------------- 4. the hit that arrives is a row you can
                                    act on ---------------------------------- */
//
// A request that fires but never renders reads to a user as "Cmd+K does
// nothing", which is the other half of why F3 and F7 are one complaint.

await section("the hit that arrives", async () => {
  const { gate, runtime } = await openPalette();
  try {
    await typeAndRun(gate, runtime, "عميل", 2);
    const list = findByTestId(gate.instance.tree, "command-list");
    const rendered = JSON.stringify(list ?? null);
    check("the search hit renders as its own command row", rendered.includes("search-customer-"), true);
  } finally {
    await gate.cleanup();
  }
});

/* ------------------------- 5. the gate can see the loop it guards against -- */
//
// This is the half that makes the four sections above worth anything.

await section("control", async () => {
  let requests = 0;
  let storm = null;
  const { gate, runtime } = await openPalette({ unstableMutate: true });
  try {
    requests = await typeAndRun(gate, runtime, "عميل", HORIZON_ROUNDS);
  } catch (err) {
    storm = err;
    requests = gate.fetches("/search").length;
  } finally {
    await gate.cleanup();
  }
  if (storm?.name !== "RenderStorm" && requests < HORIZON_ROUNDS) {
    problems.push(
      `control failed: with the mutate identity changed every render the gate still saw only ` +
        `${requests} /search requests — sections 1-4 above are therefore measuring nothing`,
    );
  } else {
    console.log(
      `  · control: same input, mutate identity changed per render -> ${requests} /search ` +
        `requests${storm ? ` and a ${storm.name}` : ""}. The gate does measure the loop.`,
    );
  }
});

if (problems.length) {
  console.error("✗ src/components/command-palette.tsx — search request count (F3)\n");
  for (const problem of problems) console.error(`  - ${problem}`);
  console.error("");
  process.exit(1);
}

console.log("✓ src/components/command-palette.tsx: one settled query, one /search (F3)");
