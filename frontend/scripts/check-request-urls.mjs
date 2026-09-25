/**
 * Assert that every browser request is aimed at ONE resolved URL, built once.
 *
 * The client has two shapes to support: same-origin (`NEXT_PUBLIC_API_URL`
 * unset, so the base is already `/api/v1` and Next rewrites it to the API) and
 * an absolute API origin (then `/api/v1` still has to be inserted). Two call
 * sites — the 401 refresh and the logout ping — each hand-built their own
 * string instead of asking the one function that knows the rule, and under the
 * DEFAULT same-origin shape both produced `/api/v1/api/v1/...`. The refresh 404s,
 * `tryRefresh` returns false, and the session is cleared on the first expired
 * token: the least-tested path in the app was also the one that logs everyone
 * out. A grep cannot see that, so this loads the real module and calls it.
 *
 * The module is TypeScript and the repo has no bundler in a test harness, so
 * this compiles `src/lib/api.ts` to memory with the project's own TypeScript
 * and imports the emitted code. That is the shipping function under test, not a
 * transcription of it — the only thing a guard like this can be and still mean
 * something.
 *
 * Run: node scripts/check-request-urls.mjs
 */

import { mkdtemp, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { pathToFileURL } from "node:url";

import ts from "typescript";

const SOURCE = "src/lib/api.ts";
const SOURCE_URL = new URL(`../${SOURCE}`, import.meta.url);

const problems = [];

async function loadApi(env) {
  const input = await readFile(SOURCE_URL, "utf8");
  const out = ts.transpileModule(input, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const dir = await mkdtemp(join(tmpdir(), "api-url-"));
  const file = join(dir, "api.mjs");
  // `API` is a module-level const read once from the environment, so the env
  // must be in place BEFORE the module evaluates, and each load has to be a
  // genuinely fresh module — hence the cache-busting query.
  if (env === null) delete process.env.NEXT_PUBLIC_API_URL;
  else process.env.NEXT_PUBLIC_API_URL = env;
  try {
    await writeFile(file, out, "utf8");
    return await import(`${pathToFileURL(file).href}?env=${encodeURIComponent(String(env))}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

function check(label, actual, expected) {
  const got = String(actual);
  const want = String(expected);
  if (got !== want) problems.push(`${label}\n    expected ${want}\n    actual   ${got}`);
}

// ---------------------------------------------------------- the resolution --
//
// Same-origin: the base ALREADY carries /api/v1, so appending it again is the
// bug. Absolute: the base has no prefix and every path must gain exactly one.

const SAME_ORIGIN = null; // NEXT_PUBLIC_API_URL unset: the default deployment shape
const ABSOLUTE = "http://127.0.0.1:8000";
const PREFIX = "/api/v1";

const shape = await loadApi(SAME_ORIGIN);
if (typeof shape?.apiUrl !== "function") {
  problems.push(
    "src/lib/api.ts must export apiUrl(path): one function that turns a route " +
      "path into a request URL. Call sites that concatenate it themselves are " +
      "how /api/v1/api/v1/auth/refresh shipped.",
  );
} else {
  check("same-origin /auth/refresh", shape.apiUrl("/auth/refresh"), `${PREFIX}/auth/refresh`);
  check("same-origin /orders", shape.apiUrl("/orders"), `${PREFIX}/orders`);
  // A caller that already spells the prefix must not get a second one.
  check("same-origin, pre-prefixed", shape.apiUrl(`${PREFIX}/orders`), `${PREFIX}/orders`);
}

const absolute = await loadApi(ABSOLUTE);
if (typeof absolute?.apiUrl === "function") {
  check("absolute /auth/refresh", absolute.apiUrl("/auth/refresh"), `${ABSOLUTE}${PREFIX}/auth/refresh`);
  check("absolute, pre-prefixed", absolute.apiUrl(`${PREFIX}/orders`), `${ABSOLUTE}${PREFIX}/orders`);
}

// ------------------------------------------------- nothing hand-builds one --
//
// The resolver is only the fix if it is the ONLY builder. A second
// `${API}${API_PREFIX}` template anywhere in the app re-creates the drift this
// file exists for — which is why this scans every source file, not just the one
// that shipped the bug.

const { fileURLToPath } = await import("node:url");
const appRoot = fileURLToPath(new URL("..", import.meta.url));
const srcRoot = fileURLToPath(new URL("../src", import.meta.url));
const source = await readFile(SOURCE_URL, "utf8");
const builderStart = source.indexOf("export function apiUrl");
// The function's own body is its last line at column 0 — a `${API}` template
// contains a `}`, so cutting at the first brace would end mid-return.
const builderBody =
  builderStart < 0 ? "" : source.slice(builderStart, source.indexOf("\n}", builderStart) + 2);

const prefixTemplate = /`[^`]*\$\{\s*(?:API|API_BASE_URL)\s*\}[^`]*\$\{\s*API_PREFIX\s*\}[^`]*`/g;

async function* walk(dirPath) {
  for (const entry of await readdir(dirPath, { withFileTypes: true })) {
    const path = join(dirPath, entry.name);
    if (entry.isDirectory()) yield* walk(path);
    else if (/\.tsx?$/.test(entry.name)) yield path;
  }
}

for await (const file of walk(srcRoot)) {
  const text = await readFile(file, "utf8");
  const isResolverFile = file.replace(/\\/g, "/").endsWith("/src/lib/api.ts");
  for (const found of text.match(prefixTemplate) ?? []) {
    if (isResolverFile && builderBody.includes(found)) continue;
    problems.push(
      `a request URL is hand-built outside apiUrl(): ${relative(appRoot, file)}\n` +
        `    ${found.trim()}\n` +
        "    route it through apiUrl() — see this file's header for what that did.",
    );
  }
}

// The base itself has one owner. `use-realtime.ts` used to read the env var with
// an absolute `http://localhost:8000` fallback — a third copy of the rule, and
// the only copy whose default pointed a deployed browser at a laptop: SSE dead
// in production while every REST call worked.

const envReads = [];
for await (const file of walk(srcRoot)) {
  const text = await readFile(file, "utf8");
  if (/process\.env\.NEXT_PUBLIC_API_URL/.test(text)) {
    envReads.push(relative(appRoot, file).replace(/\\/g, "/"));
  }
}
const allowedReaders = ["src/lib/api.ts"];
const unexpected = envReads.filter((f) => !allowedReaders.includes(f));
if (unexpected.length) {
  problems.push(
    `NEXT_PUBLIC_API_URL is read outside src/lib/api.ts: ${unexpected.join(", ")}\n` +
      "    import apiUrl() instead — a second reader always picks a second default.",
  );
}

// -------------------------------------- nothing feeds a relative path to URL --
//
// `apiUrl()` is allowed — deliberately — to answer with a RELATIVE path, because
// that is the default same-origin deployment (and the assertions above pin it).
// But the URL constructor accepts only an ABSOLUTE argument, so handing it an
// `apiUrl()` result type-checks, builds, passes every other rule in this file,
// and then throws `TypeError: Failed to construct 'URL': Invalid URL` in the
// browser. That is the regression this rule exists for: in the 2026-09-23→24
// window `use-realtime.ts` was moved onto `apiUrl()` for exactly the reason
// above, its module-level absolute default disappeared with it, and the
// single-argument `URL` call three lines later started throwing on every mount.
// The throw landed inside the notifications bell's effect, the dashboard
// layout's `ErrorBoundary` swallowed the whole `Shell` with it, and
// `frontend-e2e` began dying test after test on `toBeVisible()` failures that
// never mentioned a URL. See the header of src/lib/use-realtime.ts for the
// full post-mortem.
//
// The rule: a one-argument URL construction is only sound when that argument is
// provably absolute. `absoluteApiUrl()` is the one app-side call that guarantees
// it; a location read is the document's own absolute URL. Anything else has to
// name its base as the second argument.
//
// An EMPTY argument is read as prose, not code — write `new URL()` in a comment
// and this stays quiet.

const ABSOLUTE_ARG = [
  /^absoluteApiUrl\s*\(/,
  /^(?:globalThis\.)?window\.location\.href$/,
  /^document\.baseURI$/,
  /^["'`]https?:\/\//,
];

/** The argument list of the call whose "(" sits at `open`, split on TOP-LEVEL
 *  commas only, or null if the text never closes. */
function callArgs(text, open) {
  let depth = 0;
  let current = "";
  const parts = [];
  for (let i = open; i < text.length; i++) {
    const ch = text[i];
    if (ch === "(" || ch === "[" || ch === "{") {
      depth += 1;
      if (depth === 1) continue;
    } else if (ch === ")" || ch === "]" || ch === "}") {
      depth -= 1;
      if (depth === 0) return [...parts, current];
    } else if (ch === "," && depth === 1) {
      parts.push(current);
      current = "";
      continue;
    }
    current += ch;
  }
  return null;
}

for await (const file of walk(srcRoot)) {
  const text = await readFile(file, "utf8");
  const rel = relative(appRoot, file).replace(/\\/g, "/");
  for (const found of text.matchAll(/\bnew\s+URL\s*\(/g)) {
    const args = callArgs(text, found.index + found[0].length - 1);
    if (args === null) {
      problems.push(`${rel}: an unparsable URL construction — make it a two-argument call`);
      continue;
    }
    if (args.length > 1) continue; // the base is stated, which is the whole rule
    const arg = args[0].trim();
    if (!arg || ABSOLUTE_ARG.some((re) => re.test(arg))) continue;
    problems.push(
      `${rel}: new URL(${arg}) is given no base.\n` +
        "    apiUrl() may answer with a relative path and the URL constructor throws on one —\n" +
        "    pass the base as the second argument, or use absoluteApiUrl(path, origin).",
    );
  }
}

// --------------------------------- the realtime URL, resolved both ways --
//
// The static rule above says a base is present. This says the result is the URL
// the browser should actually open, by importing the SHIPPING `use-realtime.ts`
// (through the same chain builder `check:palette` mounts with) and calling its
// `sseUrl()` under both deployment shapes. It needs no port, no browser and no
// dev server, which is the point: this is the one place the crash could be
// reproduced on every push, and the e2e job that finally caught it is the only
// step that runs after `npm run build`.

const { createGate } = await import("./lib/browser-chain.mjs");

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const srcPath = (p) => join(ROOT, "src", p);
const ORIGIN = "https://app.test";
const STREAMS = ["notification.events", "conversation.events"];

async function realtimeUrl(env, label, expected) {
  if (env === null) delete process.env.NEXT_PUBLIC_API_URL;
  else process.env.NEXT_PUBLIC_API_URL = env;

  let gate;
  try {
    gate = await createGate({
      entry: srcPath("lib/use-realtime.ts"),
      chain: [srcPath("lib/api.ts")],
      // Nothing here may reach the network: `sseUrl` is a pure resolution.
      fetch: async (url) => {
        throw new Error(`the gate fetched ${url} — resolution is not supposed to connect`);
      },
    });
  } catch (err) {
    problems.push(`${label}: the gate could not load src/lib/use-realtime.ts: ${err?.stack ?? err}`);
    return;
  }

  try {
    if (gate.problems.length) {
      problems.push(`${label}: the gate could not resolve the chain: ${gate.problems.join("; ")}`);
      return;
    }
    if (typeof gate.module?.sseUrl !== "function") {
      problems.push(
        `${label}: src/lib/use-realtime.ts exports no sseUrl(origin, {streams, cursor}) —\n` +
          "    the module that builds the event-stream URL and this guard have diverged.",
      );
      return;
    }
    let href = null;
    let threw = null;
    try {
      href = gate.module.sseUrl(ORIGIN, { streams: STREAMS, cursor: "evt-7" }).href;
    } catch (err) {
      threw = err;
    }
    if (threw) {
      problems.push(
        `${label}: building the event-stream URL threw ${threw}.\n` +
          "    connect() calls this inside the notifications bell's effect, so a throw here\n" +
          "    takes down the whole Shell — every dashboard route renders the error boundary.",
      );
      return;
    }
    check(`${label} stream URL`, href, expected);
  } finally {
    await gate.cleanup();
  }
}

const QUERY = "?streams=notification.events&streams=conversation.events&cursor=evt-7";

await realtimeUrl(SAME_ORIGIN, "same-origin", `${ORIGIN}${PREFIX}/realtime/events${QUERY}`);
await realtimeUrl(ABSOLUTE, "absolute base", `${ABSOLUTE}${PREFIX}/realtime/events${QUERY}`);
delete process.env.NEXT_PUBLIC_API_URL;

// The control, and the reason the two assertions above are worth anything: if
// `apiUrl()` answered the default shape with something absolute, a one-argument
// URL construction would be safe and this whole section would pass forever
// without measuring the defect it guards.
{
  const shape = await loadApi(SAME_ORIGIN);
  let threw = null;
  try {
    new URL(shape.apiUrl("/realtime/events"));
  } catch {
    threw = "threw";
  }
  if (!threw) {
    problems.push(
      "control failed: under the same-origin shape apiUrl() returned something a baseless " +
        "URL construction accepts, so `new URL` is not the hazard this file guards and the " +
        "sections above are passing for the wrong reason.",
    );
  } else {
    console.log(
      "  · control: the same-origin apiUrl() output is relative, and resolving it without a " +
        "base really does throw. The guard above measures the crash it exists for.",
    );
  }
}

if (problems.length) {
  console.error(`✗ ${SOURCE} request URLs\n`);
  for (const problem of problems) console.error(`  - ${problem}`);
  console.error("");
  process.exit(1);
}

console.log(`✓ ${SOURCE}: every request URL comes from apiUrl(), both shapes`);
console.log(`✓ src/lib/use-realtime.ts: the event-stream URL is absolute under both shapes`);
