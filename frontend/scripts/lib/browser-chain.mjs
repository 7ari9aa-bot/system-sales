/**
 * Builds a runnable chain out of the REAL browser modules so a gate can drive a
 * component end to end in Node:
 *
 *   entry.tsx -> src/lib/queries.ts -> src/lib/api.ts -> globalThis.fetch
 *
 * `check-token-storage.mjs` proves one exported function by transpiling one
 * file. That stops at the first import, and a component's defect usually lives
 * in what it does with a hook's return value — so the gate has to resolve the
 * same modules the browser does. Every `src/` file is transpiled and executed
 * exactly as shipped (only bare specifiers are rewritten, and only at the
 * boundary of a third-party package), which means a guard deleted from
 * `command-palette.tsx` or `queries.ts` fails the gate.
 *
 * Scratch lives under `node_modules/.hook-gate/` on purpose: from there Node
 * still resolves the real `clsx` / `tailwind-merge`, so `@/lib/utils` is shipping
 * code too rather than a stub that happens to agree with it.
 *
 * `@tanstack/react-query` is the one hand-written piece, because the package
 * needs a React it does not have here. It reproduces the two behaviours these
 * gates depend on, read off `node_modules/@tanstack/react-query/build/modern/
 * useMutation.js` and `@tanstack/query-core/build/modern/mutationObserver.js`
 * at v5.103.1: `mutate`/`reset` are bound once in the observer constructor, so
 * their identity is STABLE across renders, while the surrounding result object
 * is a fresh value each render. If that fidelity is wrong the F3 gate is
 * meaningless, so `check-command-palette-search.mjs` re-runs the same scenario
 * against a deliberately UNSTABLE identity and requires the gate to report the
 * storm — a gate that cannot see the bug it guards is defect O4 repeating.
 */

import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import ts from "typescript";

import { createReact } from "./hook-harness.mjs";

/** Where this project's `src/` lives. `URL.pathname` percent-encodes the space
 *  in `D:/sales system`, and `fileURLToPath` keeps the trailing separator and
 *  switches to backslashes — either one silently breaks the path comparisons
 *  below, so the value is normalized once here. */
const FRONTEND_ROOT = normUrl(fileURLToPath(new URL("../..", import.meta.url)));

function normUrl(p) {
  return String(p).replace(/\\/g, "/").replace(/\/+$/, "");
}

const REACT_STUB = /* js */ `
const react = globalThis.__gate.react;
export default react;
${["useState", "useRef", "useCallback", "useMemo", "useEffect", "useLayoutEffect",
  "useSyncExternalStore", "useId", "createContext", "useContext", "createElement",
  "memo", "Fragment", "useReducer"]
  .map((n) => `export const ${n} = react.${n};`)
  .join("\n")}
`;

const JSX_RUNTIME_STUB = /* js */ `
const rt = globalThis.__gate.jsxRuntime;
export const jsx = rt.jsx;
export const jsxs = rt.jsxs;
export const Fragment = rt.Fragment;
`;

/** The subset of v5.103's `useMutation` these gates depend on — see the header. */
const TANSTACK_STUB = /* js */ `
const react = globalThis.__gate.react;

export function useMutation(options) {
  const slot = react.useRef(undefined);
  if (slot.current === undefined) {
    const observer = {
      state: { status: "idle", data: undefined, error: null, variables: undefined },
      seq: 0,
    };
    observer.reset = () => {
      observer.state = { status: "idle", data: undefined, error: null, variables: undefined };
      observer.seq++;
      globalThis.__gate.rerender();
    };
    observer.mutate = (variables, handlers) => {
      const seq = ++observer.seq;
      observer.state = { status: "pending", data: undefined, error: null, variables };
      globalThis.__gate.rerender();
      Promise.resolve()
        .then(() => observer.options.mutationFn(variables))
        .then(
          (data) => {
            if (seq !== observer.seq) return;
            observer.state = { status: "success", data, error: null, variables };
            handlers?.onSuccess?.(data, variables, undefined);
            handlers?.onSettled?.(data, null, variables);
          },
          (error) => {
            if (seq !== observer.seq) return;
            observer.state = { status: "error", data: undefined, error, variables };
            handlers?.onError?.(error, variables, undefined);
            handlers?.onSettled?.(undefined, error, variables);
          },
        )
        .finally(() => globalThis.__gate.rerender());
      return undefined;
    };
    slot.current = observer;
  }
  const observer = slot.current;
  observer.options = options;
  const s = observer.state;
  // v5.103 binds mutate/reset once in MutationObserver's constructor, so a
  // component may list them in an effect's deps. unstableMutate switches that
  // guarantee off — the pre-fix shape a gate's control section needs.
  const stableIdentity = globalThis.__gate?.unstableMutate !== true;
  const freshMutate = (variables, handlers) => observer.mutate(variables, handlers);
  const freshReset = () => observer.reset();
  return {
    mutate: stableIdentity ? observer.mutate : freshMutate,
    mutateAsync: stableIdentity ? observer.mutate : freshMutate,
    reset: stableIdentity ? observer.reset : freshReset,
    data: s.data,
    error: s.error,
    variables: s.variables,
    status: s.status,
    isPending: s.status === "pending",
    isSuccess: s.status === "success",
    isError: s.status === "error",
    isIdle: s.status === "idle",
  };
}

export function useQuery() {
  throw new Error("this gate never renders a useQuery hook");
}
export function useInfiniteQuery() {
  throw new Error("this gate never renders an useInfiniteQuery hook");
}
export function useMutationState() {
  return [];
}
export function useQueryClient() {
  return globalThis.__gate.queryClient;
}
export const keepPreviousData = "previous";
export const isCancelledError = () => false;
`;

/** UI packages the gate replaces wholesale: exports are minted from the import. */
const AUTO_STUB_PACKAGES = new Set([
  "lucide-react",
  "@radix-ui/react-dialog",
  "@radix-ui/react-dropdown-menu",
  "@radix-ui/react-tabs",
  "@radix-ui/react-toast",
  "@radix-ui/react-slot",
  "@radix-ui/react-direction",
  "@tanstack/react-table",
  "next/link",
  "next/image",
  "next/navigation",
  "next-themes",
]);

const HAND_STUBS = {
  "@tanstack/react-query": TANSTACK_STUB,
  "@/components/ui/toast": /* js */ `
    export function toast(x) { globalThis.__gate.toasts.push(x); }
    export function Toaster() { return null; }
  `,
};

function transpile(source, fileName) {
  return ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
      jsx: "react-jsx",
    },
    fileName,
  }).outputText;
}

function bareSpecifiers(code) {
  const found = new Set();
  for (const m of code.matchAll(/(?:^|\n)\s*(?:import|export)[^"'\n]*?from\s*"([^"]+)"/g)) {
    if (!m[1].startsWith(".")) found.add(m[1]);
  }
  for (const m of code.matchAll(/import\s*\(\s*"([^"]+)"\s*\)/g)) {
    if (!m[1].startsWith(".")) found.add(m[1]);
  }
  return found;
}

/** Names a component imports from an auto-stubbed package. */
function importedNames(code, specifier) {
  const names = new Set();
  const esc = specifier.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  for (const m of code.matchAll(new RegExp(`import\\s+([^;]*?)\\s+from\\s*"${esc}"`, "g"))) {
    const clause = m[1];
    const braces = clause.match(/\{([^}]*)\}/);
    if (braces) {
      for (const part of braces[1].split(",")) {
        const t = part.trim();
        if (!t) continue;
        const [orig, alias] = t.split(/\s+as\s+/);
        names.add((alias ?? orig).trim());
      }
    }
    const def = clause.replace(/\{[^}]*\}/, "").replace(/,/g, "").trim();
    if (def && !def.startsWith("*")) names.add("__default__");
    const ns = clause.match(/\*\s+as\s+(\w+)/);
    if (ns) names.add(`${ns[1]}__ns__`);
  }
  return names;
}

function autoStubSource(specifier, names) {
  const parts = [
    `const node = (props) => globalThis.__gate.h("div", props, props && props.children);`,
  ];
  for (const n of names) {
    if (n === "__default__") parts.push(`export default node;`);
    else if (n.endsWith("__ns__")) {
      parts.push(`export const ${n.replace("__ns__", "")} = new Proxy({}, { get: () => node });`);
    } else parts.push(`export const ${n} = node;`);
  }
  return parts.join("\n");
}

function fakeResponse({ status = 200, body, headers = {} }) {
  const get = (k) => {
    const hit = Object.keys(headers).find((h) => h.toLowerCase() === String(k).toLowerCase());
    return hit ? headers[hit] : null;
  };
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get },
    json: async () => (body === undefined ? undefined : JSON.parse(JSON.stringify(body))),
    text: async () => (typeof body === "string" ? body : JSON.stringify(body ?? "")),
    body: null,
  };
}

/** A `Response` whose `body` streams the given SSE chunks and then closes. */
function streamResponse(chunks, { status = 200 } = {}) {
  const encoded = chunks.map((c) => new TextEncoder().encode(c));
  let i = 0;
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => null },
    json: async () => ({}),
    body: {
      getReader() {
        return {
          async read() {
            if (i >= encoded.length) return { done: true, value: undefined };
            return { done: false, value: encoded[i++] };
          },
          async cancel() {
            i = encoded.length;
          },
        };
      },
      async cancel() {
        i = encoded.length;
      },
    },
  };
}

/**
 * Compiles the chain and hands back a mountable module.
 *
 * `chain` lists `src/` paths that must be the shipping modules rather than
 * stubs (their own imports are followed recursively). Anything imported that is
 * neither a chained `src/` file, an auto-stubbed UI package, nor listed in
 * `stubs` is a hard problem: silently stubbing an unlisted module is how a gate
 * starts passing for the wrong reason.
 */
async function createGate({ entry, chain = [], stubs = {}, fetch, searchParams, tokens, react }) {
  const runtime = react ?? createReact();
  const dir = await mkdtempSync();
  const problems = [];
  const calls = [];
  const listeners = {};

  const storage = new Map();
  if (tokens) storage.set("sales_os_tokens", JSON.stringify(tokens));

  const saved = {
    fetch: globalThis.fetch,
    setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout,
    window: globalThis.window,
    localStorage: globalThis.localStorage,
  };

  let instance = null;

  const win = {
    localStorage: {
      getItem: (k) => (storage.has(k) ? storage.get(k) : null),
      setItem: (k, v) => storage.set(k, String(v)),
      removeItem: (k) => storage.delete(k),
    },
    setTimeout: (fn, ms, ...args) => runtime.scheduleTimer(fn, ms, args),
    clearTimeout: (id) => runtime.clearTimer(id),
    setInterval: (fn, ms, ...args) => runtime.scheduleInterval(fn, ms, args),
    clearInterval: (id) => runtime.clearTimer(id),
    addEventListener: (type, fn) => {
      (listeners[type] ??= []).push(fn);
    },
    removeEventListener: () => {},
    location: {
      origin: "https://app.test",
      href: "https://app.test/inbox",
      set href(v) {
        calls.push({ kind: "navigate", href: v });
      },
      get href() {
        return "https://app.test/inbox";
      },
    },
  };

  globalThis.__gate = {
    react: runtime.react,
    jsxRuntime: runtime.jsxRuntime,
    h: (type, props, children) => ({
      type,
      props: props ?? {},
      children: children === null || children === undefined ? [] : [children].flat(Infinity),
    }),
    navigation: { push: (href) => calls.push({ kind: "navigate", href }) },
    searchParams: searchParams ?? new URLSearchParams(),
    toasts: [],
    queryClient: {
      invalidateQueries: (f) => calls.push({ kind: "invalidate", ...f }),
      getQueryData: () => undefined,
      setQueryData: () => {},
    },
    rerender: () => {
      if (!instance || instance.destroyed) return;
      instance.dirty = true;
      runtime.pump?.();
    },
  };

  globalThis.window = win;
  globalThis.localStorage = win.localStorage;
  globalThis.setTimeout = win.setTimeout;
  globalThis.clearTimeout = win.clearTimeout;
  globalThis.fetch = async (url, init = {}) => {
    const record = { kind: "fetch", url: String(url), init, at: runtime.now() };
    calls.push(record);
    if (!fetch) throw new Error(`gate has no fetch handler for ${record.url}`);
    return fetch(record.url, init);
  };

  /* ------------------------------------------------------- module graph */

  const chainedPaths = new Set(chain.map((p) => norm(p)));
  const moduleFiles = new Map(); // specifier -> "./name.mjs"
  const emitted = new Map(); // file name -> code
  const passedThrough = new Set(); // bare npm specifiers left for Node to resolve

  function norm(p) {
    return String(p).replace(/\\/g, "/");
  }

  function srcPathOf(specifier) {
    if (!specifier.startsWith("@/")) return null;
    const rel = specifier.slice(2);
    for (const ext of [".ts", ".tsx"]) {
      const candidate = norm(`${FRONTEND_ROOT}/src/${rel}${ext}`);
      if (chainedPaths.has(candidate)) return candidate;
    }
    return null;
  }

  async function materializeSrc(path) {
    if (moduleFiles.has(path)) return moduleFiles.get(path);
    const name = `${path.split("/").pop().replace(/\.[^.]+$/, "")}-${hash(path)}.mjs`;
    moduleFiles.set(path, `./${name}`);
    const source = await readFile(path, "utf8");
    const code = transpile(source, path);
    for (const spec of bareSpecifiers(code)) {
      await resolveSpecifier(spec, code);
    }
    emitted.set(name, code);
    return `./${name}`;
  }

  async function resolveSpecifier(spec, importerCode) {
    if (moduleFiles.has(spec)) return moduleFiles.get(spec);
    if (spec === "react") {
      moduleFiles.set(spec, "./react.mjs");
      emitted.set("react.mjs", REACT_STUB);
      return "./react.mjs";
    }
    if (spec === "react/jsx-runtime") {
      moduleFiles.set(spec, "./jsx-runtime.mjs");
      emitted.set("jsx-runtime.mjs", JSX_RUNTIME_STUB);
      return "./jsx-runtime.mjs";
    }
    let source = stubs[spec] ?? HAND_STUBS[spec];
    if (source === undefined && AUTO_STUB_PACKAGES.has(spec)) {
      source = autoStubSource(spec, importedNames(importerCode ?? "", spec));
    }
    if (source !== undefined) {
      const name = `stub-${spec.replace(/[^a-zA-Z0-9]+/g, "-")}.mjs`;
      moduleFiles.set(spec, `./${name}`);
      emitted.set(name, source);
      return `./${name}`;
    }
    const chained = srcPathOf(spec);
    if (chained) {
      const target = await materializeSrc(chained);
      moduleFiles.set(spec, target);
      return target;
    }
    if (spec.startsWith("@/") || spec.startsWith("~/")) {
      problems.push(`nothing in ${chainLabel()} resolves "${spec}": add its src/ path to chain`);
      moduleFiles.set(spec, "./unresolved.mjs");
      return "./unresolved.mjs";
    }
    // A plain npm package the scratch dir can resolve for real: the run lives
    // under `node_modules/.hook-gate/`, so Node's own lookup finds it. Passing
    // `clsx`/`tailwind-merge` through keeps `@/lib/utils` shipping code rather
    // than a stub that happens to agree with it. A package that needs a React
    // context has to be stubbed explicitly, and `passedThrough` records the
    // choice so no gate resolves a third-party module by accident.
    passedThrough.add(spec);
    return null;
  }

  function chainLabel() {
    return [...chainedPaths].join(", ") || "the chain";
  }

  // Entry first, then its whole transitive closure.
  const entryPath = norm(entry);
  chainedPaths.add(entryPath);
  const entryTarget = await materializeSrc(entryPath);
  for (const spec of [...moduleFiles.keys()]) await resolveSpecifier(spec, "");

  function replaceAll(code) {
    let out = code;
    const specs = [...moduleFiles.entries()].sort((a, b) => b[0].length - a[0].length);
    for (const [spec, target] of specs) {
      const esc = spec.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      out = out
        .replace(new RegExp(`(from\\s*)"${esc}"`, "g"), `$1"${target}"`)
        .replace(new RegExp(`(import\\s*\\()"${esc}"\\)`, "g"), `$1"${target}")`);
    }
    return out;
  }

  emitted.set("unresolved.mjs", `throw new Error("gate: unstubbed import");`);
  for (const [name, code] of emitted) {
    await writeFile(join(dir, name), replaceAll(code), "utf8");
  }

  const entryFile = entryTarget.slice(2);
  const mod = await import(`${pathToFileURL(join(dir, entryFile)).href}?t=${Date.now()}`);

  const api = {
    dir,
    module: mod,
    runtime,
    react: runtime.react,
    calls,
    problems,
    storage,
    listeners,
    fetches: (needle) => calls.filter((c) => c.kind === "fetch" && (needle === undefined || c.url.includes(needle))),
    navigations: () => calls.filter((c) => c.kind === "navigate"),
    mount(component, props) {
      instance = runtime.mount(component, props);
      return instance;
    },
    get instance() {
      return instance;
    },
    /** Lets queued promise callbacks land, then re-renders. */
    async flush() {
      for (let i = 0; i < 10; i++) await Promise.resolve();
      globalThis.__gate.rerender();
    },
    async cleanup() {
      if (instance) instance.destroyed = true;
      globalThis.fetch = saved.fetch;
      globalThis.setTimeout = saved.setTimeout;
      globalThis.clearTimeout = saved.clearTimeout;
      if (saved.window === undefined) delete globalThis.window;
      else globalThis.window = saved.window;
      if (saved.localStorage === undefined) delete globalThis.localStorage;
      else globalThis.localStorage = saved.localStorage;
      delete globalThis.__gate;
      await rm(dir, { recursive: true, force: true });
    },
  };
  globalThis.__gate.api = api;
  return api;
}

function hash(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h).toString(36);
}

async function mkdtempSync() {
  const { mkdir } = await import("node:fs/promises");
  const root = join(FRONTEND_ROOT, "node_modules", ".hook-gate");
  await mkdir(root, { recursive: true });
  return mkdtemp(join(root, "run-"));
}

export { createGate, fakeResponse, streamResponse, transpile, FRONTEND_ROOT, sep };
