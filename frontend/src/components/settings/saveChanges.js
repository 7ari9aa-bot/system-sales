/**
 * The two writes of one Save, and what each of them actually did.
 *
 * A settings screen can hold two kinds of change at once: values this member may write (sent
 * to `/settings/bulk`) and APPROVAL_REQUIRED values (filed as a change request). They are two
 * requests, so they can succeed and fail INDEPENDENTLY — and the screen used to treat them as
 * one. When the request call failed after the bulk call had landed, it said "could not save",
 * left the saved keys dirty, and a retry re-sent them with revisions that were already stale,
 * which came back as a 409. The person was told their edit failed twice while it was stored.
 *
 * So the order is fixed and each step reports itself: the direct write first, then the
 * request. `errorPhase` says which half refused, so the caller can keep the half that saved
 * and re-read the page instead of pretending nothing happened.
 *
 * Pure and injectable (`api`) so the failure path is testable without a browser: this is
 * exactly the branch that was wrong, and it is the branch a static render cannot reach.
 */
export async function applySave({
  api,
  direct = {},
  needsApproval = {},
  scope,
  scopeId = null,
  expectedIds = {},
}) {
  const outcome = { saved: [], pending: [], failed: [], error: null, errorPhase: null, request: null };

  if (Object.keys(direct).length > 0) {
    try {
      await api("/settings/bulk", {
        method: "POST",
        body: {
          scope,
          ...(scopeId ? { scope_id: scopeId } : {}),
          settings: direct,
          ...(Object.keys(expectedIds).length > 0 ? { expected_history_ids: expectedIds } : {}),
        },
      });
      outcome.saved = Object.keys(direct);
    } catch (error) {
      outcome.failed = Object.keys(direct);
      outcome.error = error;
      outcome.errorPhase = "direct";
      // Nothing was stored, so the request half must not be attempted: filing a change for
      // values the person still has to fix would approve a screen that never saved.
      return outcome;
    }
  }

  if (Object.keys(needsApproval).length > 0) {
    try {
      outcome.request = await api("/settings/change-requests", {
        method: "POST",
        body: {
          changes: needsApproval,
          scope,
          ...(scopeId ? { scope_id: scopeId } : {}),
        },
      });
      outcome.pending = Object.keys(needsApproval);
    } catch (error) {
      outcome.failed = [...outcome.failed, ...Object.keys(needsApproval)];
      outcome.error = error;
      outcome.errorPhase = "request";
    }
  }

  return outcome;
}
