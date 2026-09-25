/**
 * Assert that unreadable stored tokens fall back to "signed out" (gap F2).
 *
 * `getTokens()` is the first thing every dashboard route does: the shell guard
 * calls it, `useMe` gates on it, and every request reads its access token from
 * it. It used to `JSON.parse` bare, so one malformed byte in
 * `localStorage["sales_os_tokens"]` — a truncated write, a browser extension
 * editing the key, a paste into devtools — threw on the first read of every
 * route. Nothing rendered, so nothing caught it: the whole dashboard went white
 * on the strength of one character.
 *
 * `check-request-urls.mjs` already proved this file's browser-only claim can be
 * tested for real here: the e2e suite needs a dev server, and this environment
 * cannot bind a port, so `npm run test:e2e` never runs locally. This does, and
 * it loads the shipping module rather than a transcription of it — a
 * try/catch deleted from `src/lib/api.ts` fails this and nothing else would
 * until a merchant hit a blank page.
 *
 * Run: node scripts/check-token-storage.mjs
 */

import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import ts from "typescript";

const SOURCE = "src/lib/api.ts";
const SOURCE_URL = new URL(`../${SOURCE}`, import.meta.url);
const KEY = "sales_os_tokens";

const problems = [];

/** The minimum `window` the module touches: a localStorage over a live Map —
 *  the same object the caller inspects afterwards, so removals are visible. */
function installWindow(store = new Map()) {
  globalThis.window = {
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
    },
  };
  return store;
}

/** Fresh module instance, with `window` already in place or deliberately absent. */
async function loadApi(store) {
  const input = await readFile(SOURCE_URL, "utf8");
  const out = ts.transpileModule(input, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: "es2022" },
  }).outputText;
  const dir = await mkdtemp(join(tmpdir(), "api-storage-"));
  const file = join(dir, "api.mjs");
  if (store === null) delete globalThis.window;
  else installWindow(store);
  try {
    await writeFile(file, out, "utf8");
    // Cache-busting query: each load must be a genuinely fresh module evaluation.
    return await import(`${pathToFileURL(file).href}?t=${Date.now()}-${Math.random()}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

function check(label, actual, expected) {
  if (actual !== expected) problems.push(`${label}\n    expected ${expected}\n    actual   ${actual}`);
}

/** The whole point of the gap: evaluating the module, and reading it back, must
 *  not throw — whatever is sitting in the key. */
async function read(label, raw, expected) {
  const store = new Map(raw === null ? [] : [[KEY, raw]]);
  let api;
  try {
    api = await loadApi(store);
  } catch (err) {
    problems.push(`${label}: importing ${SOURCE} threw ${err}`);
    return;
  }
  if (typeof api?.getTokens !== "function") {
    problems.push(`${SOURCE} must export getTokens(): the shell guard reads it`);
    return;
  }
  let tokens;
  let threw = null;
  try {
    tokens = api.getTokens();
  } catch (err) {
    threw = err;
  }
  if (threw) {
    problems.push(`${label}: getTokens() threw ${threw} — one bad byte blanks the dashboard`);
    return;
  }
  check(`${label} -> signed out`, tokens === null ? null : JSON.stringify(tokens), expected);
}

// ------------------------------------------------------------ unreadable in --

await read("absent key", null, null);
await read("empty value", "", null);
await read("truncated object", '{"access_token":"a","refresh_token":"b"', null);
await read("not JSON at all", "access-token-a", null);
await read("JSON null", "null", null);
await read("JSON number", "123", null);
await read("JSON string", '"just-a-token"', null);
await read("JSON array", '[{"access_token":"a"}]', null);
await read("object with no access token", '{"refresh_token":"b"}', null);

// ------------------------------------------------------------ readable in --

await read(
  "a valid pair",
  JSON.stringify({ access_token: "a", refresh_token: "b" }),
  JSON.stringify({ access_token: "a", refresh_token: "b" }),
);

// ------------------------------------------- the garbage gets swept out --
//
// Returning null is half of it. If the unreadable value stayed in storage, every
// later read re-decodes the same broken blob, and a login that only writes
// `access_token` would never clear it either.

const swept = new Map([[KEY, "{oops"]]);
const sweptApi = await loadApi(swept);
try {
  sweptApi.getTokens();
} catch (err) {
  problems.push(`the unreadable blob made getTokens() throw: ${err}`);
}
check("the unreadable blob is removed from storage", swept.has(KEY), false);

// A value that PARSES to something with no access token is not garbage — it
// decodes to "no session" every time, so it is answered, not rewritten.
const left = new Map([[KEY, "null"]]);
const leftApi = await loadApi(left);
check("a parseable empty value reads as signed out", leftApi.getTokens(), null);
check("and is left in storage", left.has(KEY), true);

const valid = new Map([[KEY, JSON.stringify({ access_token: "a", refresh_token: "b" })]]);
const validApi = await loadApi(valid);
validApi.getTokens();
check("a readable pair is left alone", valid.size, 1);

// ------------------------------------------------------------------ round trip --

const write = new Map();
const writeApi = await loadApi(write);
writeApi.setTokens({ access_token: "a", refresh_token: "b" });
check("setTokens stores what getTokens reads back", writeApi.getTokens()?.access_token, "a");
writeApi.setTokens(null);
check("setTokens(null) signs out", write.size, 0);

// ------------------------------------------------------- server-side rendering --

const ssr = await loadApi(null);
let ssrResult;
let ssrThrew = null;
try {
  ssrResult = ssr.getTokens();
} catch (err) {
  ssrThrew = err;
}
if (ssrThrew) problems.push(`getTokens() threw during render (no window): ${ssrThrew}`);
check("with no window, getTokens() is null", ssrResult, null);

if (problems.length) {
  console.error(`✗ ${SOURCE} token storage\n`);
  for (const problem of problems) console.error(`  - ${problem}`);
  console.error("");
  process.exit(1);
}

console.log(`✓ ${SOURCE}: unreadable stored tokens fall back to signed out, never throw`);
