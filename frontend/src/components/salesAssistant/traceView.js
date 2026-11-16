/** How to present an answer's measured timeline: each thinking round and each read, how long it
 *  took, what the model thought, and why the whole answer took what it took.
 *
 *  The server appends events while the answer is written (backend chat/trace.py): a ``start`` when
 *  a round or a read begins and an ``end`` with its measured duration (and, for a round, the
 *  model's own thinking), joined here by ``id``, plus one ``summary`` at the end. Nothing here is
 *  estimated: a duration shows only once the server measured it, and an open step says so.
 *  Plain functions so the rules are testable without a browser.
 */

/** One row per step, oldest first, with its end merged in. The summary is not a step. */
export function traceSteps(trace) {
  const byId = new Map();
  for (const ev of Array.isArray(trace) ? trace : []) {
    if (!ev || typeof ev !== "object" || ev.kind === "summary") continue;
    if (typeof ev.id !== "number" || ev.id < 1) continue;
    if (ev.kind !== "model" && ev.kind !== "tool") continue;
    const row = byId.get(ev.id) ?? { id: ev.id, kind: ev.kind, done: false };
    if (ev.phase === "start") {
      row.startedAtMs = ev.at_ms ?? 0;
      if (ev.kind === "model") row.purpose = ev.purpose || "answer";
      if (ev.kind === "tool") {
        row.tool = ev.tool ?? null;
        row.step = typeof ev.step === "string" && ev.step.trim() ? ev.step.trim() : null;
      }
    } else if (ev.phase === "end") {
      row.done = true;
      row.ms = Number.isFinite(ev.ms) ? ev.ms : null;
      row.ok = ev.ok !== false;
      if (ev.kind === "model") {
        row.reasoning = typeof ev.reasoning === "string" && ev.reasoning.trim() ? ev.reasoning : null;
        row.reasoningCut = ev.reasoning_cut === true;
        row.tokensOut = Number.isFinite(ev.tokens_out) ? ev.tokens_out : null;
        row.answered = ev.answered === true;
      }
    }
    byId.set(ev.id, row);
  }
  return [...byId.values()].sort((a, b) => a.id - b.id);
}

/** The summary the server wrote when the answer finished, or null while it is still running. */
export function traceSummary(trace) {
  const list = Array.isArray(trace) ? trace : [];
  for (let i = list.length - 1; i >= 0; i -= 1) {
    const ev = list[i];
    if (ev && ev.kind === "summary" && Number.isFinite(ev.total_ms)) return ev;
  }
  return null;
}

/** Measured thinking time: the sum of the finished rounds. */
export function thinkingMs(trace) {
  const summary = traceSummary(trace);
  if (summary && Number.isFinite(summary.model_ms)) return summary.model_ms;
  return traceSteps(trace)
    .filter((s) => s.kind === "model" && s.done && Number.isFinite(s.ms))
    .reduce((sum, s) => sum + s.ms, 0);
}

/** Seconds with one decimal, the way the owner reads them ("6.4"). */
export function seconds(ms) {
  if (!Number.isFinite(ms) || ms < 0) return "0.0";
  return (ms / 1000).toFixed(1);
}

/** What a step is called. Rounds are numbered among the ordinary rounds only, so a rewrite is
 *  named a rewrite instead of taking the next number. */
export function stepLabel(step, steps, t) {
  if (step.kind === "tool") return step.step || t("salesAssistant.trace.read");
  if (step.purpose === "rewrite") return t("salesAssistant.trace.rewrite");
  if (step.purpose === "fill_gap") return t("salesAssistant.trace.fill");
  const n = steps.filter((s) => s.kind === "model" && (s.purpose ?? "answer") === "answer" && s.id <= step.id).length;
  return t("salesAssistant.trace.round").replace("{n}", String(n));
}

/** Whether a step has thinking the owner can open. */
export function canOpen(step) {
  return step.kind === "model" && step.done && !!step.reasoning;
}
