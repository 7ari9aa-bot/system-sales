/** Shared settings hook — the single source for effective settings consumption.
 *
 * Fetches ALL effective settings and their definitions from the unified
 * `/settings/effective` and `/settings/definitions` endpoints, groups them
 * by domain (as the registry defines), and exposes a save function.
 *
 * Supports:
 * - scope/scopeId (tenant, branch, pos_profile, register, …) instead of
 *   the old hardcoded "tenant".
 * - segment filtering (retail, fnb, services, wholesale).
 * - Optimistic-concurrency: expected_history_ids are sent with every save
 *   and a 409 conflict is surfaced via `conflict` state.
 * - Change requests for APPROVAL_REQUIRED settings: create, list, approve,
 *   reject.
 * - Preview / dry-run before save.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { applySave } from "@/components/settings/saveChanges";

/**
 * Split a pending edit into what can be written now and what needs a change request.
 *
 * The bulk endpoint refuses an APPROVAL_REQUIRED key outright, so a screen holding both
 * kinds cannot be saved in one call: the request fails and the direct edits are lost with
 * it. Pure so the split is testable without a browser.
 */
export function splitSaveChanges(changes, approvalRequiredKeys = []) {
  const direct = {};
  const needsApproval = {};
  for (const [key, value] of Object.entries(changes || {})) {
    if (approvalRequiredKeys.includes(key)) needsApproval[key] = value;
    else direct[key] = value;
  }
  return { direct, needsApproval };
}

/** Scope options for the selector, matching backend `Scope` enum. */
export const SCOPE_OPTIONS = [
  { value: "tenant", labelAr: "المستوى العام", labelEn: "Tenant" },
  { value: "workspace", labelAr: "مساحة العمل", labelEn: "Workspace" },
  { value: "branch", labelAr: "فرع", labelEn: "Branch" },
  { value: "warehouse", labelAr: "مخزن", labelEn: "Warehouse" },
  { value: "pos_profile", labelAr: "ملف نقطة البيع", labelEn: "POS Profile" },
  { value: "register", labelAr: "جهاز", labelEn: "Register" },
  { value: "channel", labelAr: "قناة", labelEn: "Channel" },
  { value: "user", labelAr: "مستخدم", labelEn: "User" },
];

/** The server's redaction marker (router MASKED_VALUE) — never a value to save. */
export const MASKED_VALUE = "******";

export function isMaskedValue(value) {
  return value === MASKED_VALUE;
}

export function useSettings(opts = {}) {
  // `section`/`page` are the key's Settings Center home (docs/settings/center-map.md). A page
  // passes its own pair and receives exactly the keys it owns — not its neighbours' controls.
  const { domain, keys, segment, section, page, scope = "tenant", scopeId = null } = opts;

  const [defs, setDefs] = useState(null);
  const [values, setValues] = useState({});
  const [original, setOriginal] = useState({});
  const [historyIds, setHistoryIds] = useState({});
  /** Per key: `{ scope, scopeId, isInherited, isDefault }` — where the value in `values` came from. */
  const [sources, setSources] = useState({});
  // Bumped to re-read the page after a partial save: the stored half must be shown as stored.
  const [reloadToken, setReloadToken] = useState(0);
  const reload = useCallback(() => setReloadToken((n) => n + 1), []);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState(null); // { message, keys } | null
  // The SERVER's verdict on the pending save (/settings/preview): what would change, what is
  // out of range, and which keys need approval. A client-side diff cannot know any of that.
  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [changeRequests, setChangeRequests] = useState([]);

  // Build the query strings for definitions and effective.
  const defsQuery = useMemo(() => {
    const params = new URLSearchParams();
    if (domain) params.set("domain", domain);
    if (segment) params.set("segment", segment);
    if (section) params.set("section", section);
    if (page) params.set("page", page);
    const s = params.toString();
    return s ? `?${s}` : "";
  }, [domain, segment, section, page]);

  const effQuery = useMemo(() => {
    const params = new URLSearchParams();
    params.set("scope", scope);
    if (scopeId) params.set("scope_id", scopeId);
    if (domain) params.set("domain", domain);
    if (keys) params.set("keys", keys);
    const s = params.toString();
    return s ? `?${s}` : "";
  }, [scope, scopeId, domain, keys]);

  // Definitions lookup map for apply_mode, sensitivity, etc.
  const defMap = useMemo(() => {
    if (!defs) return {};
    const m = {};
    for (const d of defs) m[d.key] = d;
    return m;
  }, [defs]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    setConflict(null);

    Promise.all([
      api(`/settings/definitions${defsQuery}`),
      api(`/settings/effective${effQuery}`),
    ])
      .then(([defList, eff]) => {
        if (!alive) return;
        const list = Array.isArray(defList) ? defList : [];
        setDefs(list);
        const v = {};
        const hids = {};
        const src = {};
        for (const [key, resolved] of Object.entries(eff || {})) {
          v[key] = resolved.value;
          if (resolved.latest_history_id) hids[key] = resolved.latest_history_id;
          // WHERE the value came from, which the server already answers and this hook used to
          // throw away: the scope that won the resolution, whether that scope is an ancestor
          // (inherited), and whether the value is the registry default rather than anyone's
          // decision. Without it the screen showed a branch's inherited number as if the branch
          // had chosen it.
          src[key] = {
            scope: resolved.scope,
            scopeId: resolved.scope_id ?? null,
            isInherited: Boolean(resolved.is_inherited),
            isDefault: Boolean(resolved.is_default),
          };
        }
        setValues(v);
        setOriginal(v);
        setHistoryIds(hids);
        setSources(src);
        setLoading(false);
      })
      .catch((err) => {
        if (!alive) return;
        setError(err?.message || "Could not load settings");
        setLoading(false);
      });

    // Also load change requests for this scope.
    api("/settings/change-requests")
      .then((reqs) => {
        if (!alive) return;
        setChangeRequests(Array.isArray(reqs) ? reqs : []);
      })
      .catch(() => {
        // Non-fatal: change requests are optional context.
      });

    return () => { alive = false; };
  }, [defsQuery, effQuery, reloadToken]);

  const dirty = useMemo(
    () => JSON.stringify(values) !== JSON.stringify(original),
    [values, original],
  );

  // Group definitions by domain — the registry domain is the grouping key.
  const grouped = useMemo(() => {
    if (!defs) return {};
    const map = {};
    for (const d of defs) {
      if (!map[d.domain]) map[d.domain] = [];
      map[d.domain].push(d);
    }
    // Sort keys within each domain for stable display.
    for (const dom of Object.keys(map)) {
      map[dom].sort((a, b) => a.key.localeCompare(b.key));
    }
    return map;
  }, [defs]);

  const setValue = useCallback((key, value) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    setConflict(null);
  }, []);

  /** Which dirty keys are APPROVAL_REQUIRED. */
  const approvalRequiredKeys = useMemo(() => {
    const keys = [];
    for (const [k, v] of Object.entries(values)) {
      if (v !== original[k]) {
        const def = defMap[k];
        if (def?.apply_mode === "approval_required") keys.push(k);
      }
    }
    return keys;
  }, [values, original, defMap]);

  /** Build the list of changed keys with old/new values for preview. */
  const changedEntries = useMemo(() => {
    const entries = [];
    for (const [k, v] of Object.entries(values)) {
      if (v !== original[k]) {
        const def = defMap[k];
        entries.push({
          key: k,
          label: def?.label_en || k,
          oldValue: original[k],
          newValue: v,
          applyMode: def?.apply_mode || "validated",
          needsApproval: def?.apply_mode === "approval_required",
          domain: def?.domain || "",
        });
      }
    }
    return entries;
  }, [values, original, defMap]);

  /** Ask the server what this save would do, without writing it. */
  const runPreview = useCallback(async () => {
    const changed = {};
    for (const [k, v] of Object.entries(values)) {
      if (v !== original[k]) changed[k] = v;
    }
    if (Object.keys(changed).length === 0) {
      setPreview(null);
      return;
    }
    setPreviewing(true);
    try {
      const result = await api("/settings/preview", {
        method: "POST",
        body: { scope, scope_id: scopeId, settings: changed },
      });
      setPreview(result);
    } catch (err) {
      setPreview({ error: err?.message || "preview failed" });
    } finally {
      setPreviewing(false);
    }
  }, [values, original, scope, scopeId]);

  const save = useCallback(async () => {
    setSaving(true);
    setError("");
    setNotice("");
    setConflict(null);
    // A save is TWO writes, and each one either lands or does not. They used to share a single
    // try block: if the change-request call failed, the screen said "could not save" while the
    // bulk write was already stored, left the saved keys dirty, and a retry re-sent them with
    // stale revisions and collected a 409. Each half now records its own outcome and the
    // caller gets the truth: what was saved, what is pending, what failed.
    const outcome = { saved: [], pending: [], failed: [] };
    try {
      const changes = {};
      for (const [k, v] of Object.entries(values)) {
        // A redacted value is not a value: writing "******" back would overwrite the real
        // setting with the mask itself.
        if (isMaskedValue(v)) continue;
        if (v !== original[k]) changes[k] = v;
      }
      // A screen can hold both kinds at once. The bulk endpoint refuses an
      // APPROVAL_REQUIRED key outright, so sending one batch would fail the whole save and
      // the direct edits would be lost with it. Split: direct edits are written now, the
      // rest become a change request.
      const { direct, needsApproval } = splitSaveChanges(changes, approvalRequiredKeys);

      // Pass expected_history_ids for optimistic-concurrency checks (§81). Every key names the
      // revision it was read at — null for a setting that has never been written. Sending only
      // the keys that already had a revision left the first write of a fresh setting
      // unprotected: another user's first write was overwritten without a 409.
      const expectedIds = {};
      for (const k of Object.keys(direct)) expectedIds[k] = historyIds[k] ?? null;

      // The two writes and their independent outcomes live in `applySave` (pure, tested).
      const result = await applySave({
        api,
        direct,
        needsApproval,
        scope,
        scopeId,
        expectedIds,
      });
      outcome.saved = result.saved;
      outcome.pending = result.pending;
      outcome.failed = result.failed;

      if (result.saved.length > 0) {
        // Stored NOW, so these keys stop being dirty before the request half is considered: if
        // that half failed, the screen must not claim they are unsaved.
        setOriginal((prev) => {
          const next = { ...prev };
          for (const k of result.saved) next[k] = values[k];
          return next;
        });
      }
      if (result.request) {
        setChangeRequests((prev) => [result.request, ...prev]);
        // They are pending, not saved: show the stored value, not the request.
        setValues((prev) => {
          const next = { ...prev };
          for (const k of result.pending) next[k] = original[k];
          return next;
        });
      }
      if (result.error) {
        if (result.errorPhase === "request") {
          // The typed values stay in the fields so they can be sent again; the half that DID
          // save is reported as saved, never as a total failure.
          setError(result.error?.message || "Could not file the change request");
          setNotice(result.saved.length > 0 ? "saved_request_failed" : "");
          if (result.saved.length > 0) reload();
          return outcome;
        }
        throw result.error;
      }

      if (outcome.pending.length > 0 && outcome.saved.length > 0) {
        setNotice("saved_with_pending");
      } else if (outcome.pending.length > 0) {
        setNotice("change_request_submitted");
      } else {
        setNotice("saved");
      }
      return outcome;
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setConflict({
          message: err.message || "Another user edited these settings before you.",
          keys: err.details?.conflicting_keys || Object.keys(values).filter((k) => values[k] !== original[k]),
        });
      } else {
        setError(err?.message || "Could not save");
      }
      // A partial write is possible even here: the bulk call landed and something after it
      // did not. Re-read so the screen shows what the server holds, not what we hoped.
      if (outcome.saved.length > 0) reload();
      return outcome;
    } finally {
      setSaving(false);
    }
  }, [values, original, historyIds, scope, scopeId, approvalRequiredKeys, reload]);

  /** Create a change request for APPROVAL_REQUIRED settings. */
  const submitChangeRequest = useCallback(async (reason) => {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const changes = {};
      for (const k of approvalRequiredKeys) {
        if (isMaskedValue(values[k])) continue;
        changes[k] = values[k];
      }
      if (Object.keys(changes).length === 0) return;
      const req = await api("/settings/change-requests", {
        method: "POST",
        body: {
          changes,
          scope,
          ...(scopeId ? { scope_id: scopeId } : {}),
          reason: reason || undefined,
        },
      });
      setChangeRequests((prev) => [req, ...prev]);
      // Reset the approval-required keys back to original — they're now pending.
      setValues((prev) => {
        const next = { ...prev };
        for (const k of approvalRequiredKeys) next[k] = original[k];
        return next;
      });
      setNotice("change_request_submitted");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setConflict({
          message: err.message || "Another user edited these settings before you.",
          keys: approvalRequiredKeys,
        });
      } else {
        setError(err?.message || "Could not submit change request");
      }
    } finally {
      setSaving(false);
    }
  }, [approvalRequiredKeys, values, original, scope, scopeId]);

  /** Approve a pending change request (requires a second admin). */
  const approveChangeRequest = useCallback(async (requestId, reviewNote) => {
    setError("");
    try {
      const req = await api(`/settings/change-requests/${requestId}/approve`, {
        method: "POST",
        body: { review_note: reviewNote || undefined },
      });
      setChangeRequests((prev) => prev.map((r) => (r.id === requestId ? req : r)));
      setNotice("change_request_approved");
    } catch (err) {
      setError(err?.message || "Could not approve change request");
      // A stale refusal is a decision the server recorded, so the row is no longer
      // pending. Re-read the list instead of leaving a request on screen that keeps
      // failing every time someone clicks approve.
      if (String(err?.message || "").includes("stale")) {
        api("/settings/change-requests")
          .then((reqs) => setChangeRequests(Array.isArray(reqs) ? reqs : []))
          .catch(() => {});
      }
    }
  }, []);

  /** Reject a pending change request (requires a second admin). */
  const rejectChangeRequest = useCallback(async (requestId, reviewNote) => {
    setError("");
    try {
      const req = await api(`/settings/change-requests/${requestId}/reject`, {
        method: "POST",
        body: { review_note: reviewNote || undefined },
      });
      setChangeRequests((prev) => prev.map((r) => (r.id === requestId ? req : r)));
      setNotice("change_request_rejected");
    } catch (err) {
      setError(err?.message || "Could not reject change request");
    }
  }, []);

  const reset = useCallback(() => {
    setValues({ ...original });
    setConflict(null);
  }, [original]);

  return {
    defs,
    defMap,
    grouped,
    values,
    sources,
    original,
    dirty,
    loading,
    error,
    saving,
    notice,
    conflict,
    preview,
    previewing,
    runPreview,
    changeRequests,
    approvalRequiredKeys,
    changedEntries,
    scope,
    scopeId,
    setValue,
    save,
    reset,
    submitChangeRequest,
    approveChangeRequest,
    rejectChangeRequest,
  };
}
