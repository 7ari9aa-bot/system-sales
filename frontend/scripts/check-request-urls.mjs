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

if (problems.length) {
  console.error(`✗ ${SOURCE} request URLs\n`);
  for (const problem of problems) console.error(`  - ${problem}`);
  console.error("");
  process.exit(1);
}

console.log(`✓ ${SOURCE}: every request URL comes from apiUrl(), both shapes`);
