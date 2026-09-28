/**
 * A hook runtime and module loader for the `scripts/check-*.mjs` gates.
 *
 * Why this exists: the browser half of this repo is Playwright, and Playwright
 * cannot run here (it needs a dev server, and this machine cannot bind a port),
 * so an effect that only misbehaves in a browser has no local proof at all.
 * `check-token-storage.mjs` already showed that a browser-only claim CAN be
 * tested for real in Node by transpiling the shipping module — this file is the
 * same trick pushed one step further, to modules whose defect only appears once
 * React runs their hooks (an effect that re-fires, a stream that reconnects on
 * every render, a request storm out of one keystroke).
 *
 * What it is NOT: not a React implementation, and not a DOM. It supports the
 * hooks the components under test actually call, in the order React calls them,
 * with React's own bail-out rules (`Object.is` on state, shallow deps compare).
 * JSX evaluates to a plain tree a gate can walk to find a real handler and
 * invoke it, so a gate drives a component through its public input rather than
 * through a transcription of its logic.
 *
 * The ceiling is honest and worth stating: nothing here checks layout, ARIA
 * behavior, or real network conditions. It checks render- and effect-count
 * invariants — exactly the class of defect that survives both a type check and
 * a lint pass.
 */

import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import ts from "typescript";

const sameDeps = (a, b) => {
  if (a === undefined || b === undefined) return false;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (!Object.is(a[i], b[i])) return false;
  return true;
};

/** Raised instead of hanging when an effect re-triggers its own render. */
export class RenderStorm extends Error {
  constructor(renders, limit) {
    super(`rendered ${renders} times without settling (limit ${limit})`);
    this.name = "RenderStorm";
    this.renders = renders;
  }
}

/* ------------------------------------------------------------------ react */

/**
 * Creates the hook runtime plus the object that stands in for `react` and for
 * `react/jsx-runtime`.
 *
 * Time is virtual: `advance(ms)` fires only the timers that were due, so a gate
 * can say "wait 250ms" or "wait 30s of backoff" without waiting and without
 * flaking. Both `window.setTimeout` and the bare global `setTimeout` the
 * realtime client schedules its backoff through route here.
 */
export function createReact() {
  const state = {
    now: 0,
    timers: new Map(), // id -> { at, fn, args, repeatMs }
    nextTimerId: 1,
    instance: null,
  };

  function requireInstance() {
    if (!state.instance) throw new Error("hook called outside a render");
    return state.instance;
  }

  const react = {
    useState(initial) {
      const inst = requireInstance();
      const i = inst.hookIndex++;
      if (inst.hooks[i] === undefined) {
        inst.hooks[i] = {
          value: typeof initial === "function" ? initial() : initial,
        };
      }
      const slot = inst.hooks[i];
      const set = (next) => {
        const value = typeof next === "function" ? next(slot.value) : next;
        // React bails out when the new state is identical. This has to be the
        // real rule: "a setter that always re-renders" is one of the shapes F6
        // takes, and a harness that always re-rendered would report it as
        // normal and hide the bug.
        if (Object.is(value, slot.value)) return;
        slot.value = value;
        inst.dirty = true;
      };
      return [slot.value, set];
    },

    useRef(initial) {
      const inst = requireInstance();
      const i = inst.hookIndex++;
      if (inst.hooks[i] === undefined) inst.hooks[i] = { current: initial };
      return inst.hooks[i];
    },

    useCallback(fn, deps) {
      const inst = requireInstance();
      const i = inst.hookIndex++;
      const prev = inst.hooks[i];
      if (prev === undefined || !sameDeps(prev.deps, deps)) {
        inst.hooks[i] = { deps, value: fn };
      }
      return inst.hooks[i].value;
    },

    useMemo(fn, deps) {
      const inst = requireInstance();
      const i = inst.hookIndex++;
      const prev = inst.hooks[i];
      if (prev === undefined || !sameDeps(prev.deps, deps)) {
        inst.hooks[i] = { deps, value: fn() };
      }
      return inst.hooks[i].value;
    },

    useEffect(fn, deps) {
      const inst = requireInstance();
      const i = inst.hookIndex++;
      if (inst.hooks[i] === undefined) inst.hooks[i] = { deps: null, ran: false };
      const slot = inst.hooks[i];
      slot.fn = fn;
      slot.nextDeps = deps;
      inst.collected.push(slot);
    },

    useLayoutEffect(fn, deps) {
      react.useEffect(fn, deps);
    },

    useSyncExternalStore(_subscribe, getSnapshot) {
      return getSnapshot();
    },

    useId() {
      const inst = requireInstance();
      const i = inst.hookIndex++;
      if (inst.hooks[i] === undefined) inst.hooks[i] = { id: `:r${i}:` };
      return inst.hooks[i].id;
    },

    createContext(defaultValue) {
      return { _currentValue: defaultValue };
    },

    useContext() {
      return undefined;
    },

    createElement(type, props, ...children) {
      return makeElement(type, props, children);
    },

    memo(fn) {
      return fn;
    },

    Fragment: "#fragment",
  };

  /* ---------------------------------------------------------- elements */

  function makeElement(type, props, children) {
    const kids = [children].flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false);
    return { type, props: props ?? {}, children: kids };
  }

  const jsx = (type, props) => {
    const { children, ...rest } = props ?? {};
    const kids = children === undefined || children === null ? [] : [children].flat(Infinity);
    return makeElement(type, rest, kids);
  };

  const jsxRuntime = {
    jsx,
    jsxs: jsx,
    Fragment: "#fragment",
  };

  /* ------------------------------------------------------------ timers */

  function scheduleTimer(fn, ms = 0, args = []) {
    const id = state.nextTimerId++;
    state.timers.set(id, { at: state.now + Math.max(0, ms), fn, args });
    return id;
  }

  function clearTimer(id) {
    state.timers.delete(id);
  }

  function scheduleInterval(fn, ms = 0, args = []) {
    const id = scheduleTimer(fn, ms, args);
    const timer = state.timers.get(id);
    if (timer) timer.repeatMs = Math.max(1, ms);
    return id;
  }

  /** Runs every timer due within the next `ms`, in chronological order. */
  function advance(ms) {
    const target = state.now + ms;
    let fired = 0;
    for (;;) {
      let due = null;
      for (const [id, t] of state.timers) {
        if (t.at > target) continue;
        if (due === null || t.at < due.t.at || (t.at === due.t.at && id < due.id)) due = { id, t };
      }
      if (!due) break;
      if (++fired > 5_000) throw new RenderStorm(fired, 5_000);
      state.now = due.t.at;
      if (due.t.repeatMs) due.t.at = state.now + due.t.repeatMs;
      else state.timers.delete(due.id);
      due.t.fn(...due.t.args);
      api.pump();
    }
    state.now = target;
  }

  /* ------------------------------------------------------------- mount */

  const api = {
    react,
    jsxRuntime,
    now: () => state.now,
    pendingTimers: () => state.timers.size,
    scheduleTimer,
    scheduleInterval,
    clearTimer,
    advance,
    timers: state.timers,
  };

  /**
   * Renders `component(props)` until it settles, running effects between passes
   * the way React does, and throws `RenderStorm` rather than spinning forever —
   * for F3 the storm IS the finding, so a hang would be a worse report than an
   * error.
   */
  api.mount = function mount(component, props) {
    const inst = {
      component,
      props,
      hooks: [],
      hookIndex: 0,
      collected: [],
      dirty: true,
      renders: 0,
      effectRuns: 0,
      tree: null,
      destroyed: false,
    };
    state.instance = inst;

    function renderOnce() {
      inst.renders++;
      if (inst.renders > 300) {
        inst.destroyed = true;
        throw new RenderStorm(inst.renders, 300);
      }
      inst.hookIndex = 0;
      inst.collected = [];
      inst.tree = component(inst.props) ?? null;
      for (const slot of inst.collected.splice(0)) {
        const changed = !slot.ran || !sameDeps(slot.deps, slot.nextDeps ?? null);
        if (!changed) continue;
        if (typeof slot.cleanup === "function") slot.cleanup();
        slot.deps = slot.nextDeps ?? null;
        slot.ran = true;
        inst.effectRuns++;
        slot.cleanup = slot.fn();
      }
    }

    function pump(limit = 120) {
      let passes = 0;
      while (inst.dirty && !inst.destroyed) {
        if (++passes > limit) {
          inst.destroyed = true;
          throw new RenderStorm(passes, limit);
        }
        inst.dirty = false;
        renderOnce();
      }
    }

    api.pump = pump;
    api.instance = inst;
    api.rerenderWith = (nextProps) => {
      inst.props = nextProps;
      inst.dirty = true;
      pump();
    };
    api.unmount = () => {
      inst.destroyed = true;
      for (const hook of inst.hooks) {
        if (hook && typeof hook.cleanup === "function") hook.cleanup();
      }
    };

    renderOnce();
    pump();
    return inst;
  };

  return api;
}

/* ------------------------------------------------------------- jsx tree */

/** Depth-first search for a rendered element by `data-testid`. */
export function findByTestId(root, testId) {
  const seen = [];
  const walk = (node) => {
    if (!node || typeof node !== "object" || Array.isArray(node)) return;
    if (node.props && node.props["data-testid"] === testId) seen.push(node);
    if (node.children) for (const c of node.children) walk(c);
    if (node.props && node.props.children !== undefined) {
      for (const c of [node.props.children].flat(Infinity)) walk(c);
    }
  };
  walk(root);
  return seen[0] ?? null;
}

/* --------------------------------------------------------- module loader */

/**
 * Transpile a real `src/` module and import it with every bare specifier
 * replaced by something the caller controls.
 *
 * The transpile step is the point: the gate executes the same source the browser
 * executes, so deleting a guard from the shipping file fails the gate. Stubs
 * stay at the import boundary — the module under test is never rewritten.
 */
export async function loadTranspiled(file, stubs = {}, reactRuntime) {
  const source = await readFile(file, "utf8");
  const out = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
      jsx: "react-jsx",
    },
    fileName: typeof file === "string" ? file : "module.tsx",
  }).outputText;

  const dir = await mkdtemp(join(tmpdir(), "hook-gate-"));
  try {
    const rewrites = [];
    let n = 0;
    for (const [specifier, body] of Object.entries(stubs)) {
      const name = `stub${n++}.mjs`;
      const text =
        typeof body === "function" ? body(reactRuntime) : String(body);
      await writeFile(join(dir, name), text, "utf8");
      rewrites.push([specifier, `./${name}`]);
    }
    // Longest specifier first: `react/jsx-runtime` must be rewritten before
    // `react`, or the shorter match eats it.
    rewrites.sort((a, b) => b[0].length - a[0].length);
    let code = out;
    for (const [specifier, target] of rewrites) {
      const esc = specifier.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      code = code.replace(new RegExp(`(from\\s*)["']${esc}["']`, "g"), `$1"${target}"`);
      code = code.replace(new RegExp(`(import\\s*\\()["']${esc}["']\\)`, "g"), `$1"${target}")`);
      code = code.replace(new RegExp(`(export\\s*\\*\\s*from\\s*)["']${esc}["']`, "g"), `$1"${target}"`);
    }
    const entry = join(dir, "entry.mjs");
    await writeFile(entry, code, "utf8");
    return await import(`${pathToFileURL(entry).href}?t=${Date.now()}-${Math.random()}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/**
 * Installs the smallest `window` a client module touches, with the virtual clock
 * wired through both `window.setTimeout` and the global one.
 */
export function installBrowser(reactRuntime, { storage = new Map() } = {}) {
  const saved = {
    setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout,
    setInterval: globalThis.setInterval,
    clearInterval: globalThis.clearInterval,
    window: globalThis.window,
  };

  const window = {
    localStorage: {
      getItem: (k) => (storage.has(k) ? storage.get(k) : null),
      setItem: (k, v) => storage.set(k, String(v)),
      removeItem: (k) => storage.delete(k),
    },
    setTimeout: (fn, ms, ...args) => reactRuntime.scheduleTimer(fn, ms, args),
    clearTimeout: (id) => reactRuntime.clearTimer(id),
    setInterval: (fn, ms, ...args) => reactRuntime.scheduleInterval(fn, ms, args),
    clearInterval: (id) => reactRuntime.clearTimer(id),
    addEventListener: () => {},
    removeEventListener: () => {},
    location: { origin: "https://app.test", href: "https://app.test/inbox" },
  };

  globalThis.window = window;
  globalThis.localStorage = window.localStorage;
  globalThis.setTimeout = window.setTimeout;
  globalThis.clearTimeout = window.clearTimeout;

  return {
    window,
    storage,
    restore() {
      globalThis.setTimeout = saved.setTimeout;
      globalThis.clearTimeout = saved.clearTimeout;
      globalThis.setInterval = saved.setInterval;
      globalThis.clearInterval = saved.clearInterval;
      if (saved.window === undefined) delete globalThis.window;
      else globalThis.window = saved.window;
      delete globalThis.localStorage;
    },
  };
}
