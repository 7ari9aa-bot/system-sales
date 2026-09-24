"use client";

/** Decide one parked HIGH-risk action: `POST /ai/approvals/{id}/decide`.
 *
 *  A decision is a WRITE, so it follows the same discipline as the order dialogs
 *  (`../orders/refund-dialog.tsx`) without borrowing their money copy:
 *
 *  * ONE Idempotency-Key per dialog OPEN (`useDialogIdempotencyKey`), re-sent
 *    unchanged on a react-query retry and across a 401→refresh. Replaying an
 *    approval decision with a FRESH key is precisely how the same action could be
 *    granted twice, so a terminal answer keeps the key and stops submitting —
 *    the only path to a new key is closing and reopening (a new intent).
 *  * The two buttons map to the server's OWN vocabulary — `APPROVED` / `REJECTED`
 *    on a single `decide` route (router.py:320-359), not separate endpoints.
 *  * A reason is collected on DENY only, and sent under the field the request
 *    model reads — `reason` (router.py:286). The previous screen sent
 *    `rejection_reason`, which the server dropped, and it invented a reason text;
 *    `buildDecisionPayload` omits a blank one instead (the server's field is
 *    optional, so a deny with no reason is legal and honest).
 *  * `ApprovalService.decide` answers an already-decided or expired approval with
 *    a 400, not a 409 (`approvals.py:131-138`, `errors.py:65-68`), and this route
 *    is NOT on the idempotency allow-list (`idempotency.py:115-123`) — so
 *    `classifyDecisionError` treats those "can no longer be decided" sentences as
 *    terminal rather than resendable.
 *
 *  The screen does NOT pre-check permission client-side: there is no permission
 *  model on the client to consult (`require_permission("settings:write")` runs on
 *  the server, router.py:324), so an action the reviewer cannot take is discovered
 *  on the click and its 403 sentence is shown verbatim, with the submit left
 *  enabled because nothing ran. */

import * as React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiWithMeta, type ApiResponse } from "@/lib/api";
import { qk, type Approval } from "@/lib/queries";
import { toast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Label, Textarea } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useDialogIdempotencyKey } from "@/lib/use-dialog-idempotency";
import { ap } from "./labels";
import {
  DENY,
  DECISION_REASON_MAX,
  buildDecisionPayload,
  classifyDecisionError,
  type Decision,
  type DecisionPayload,
  type DecisionRefusal,
} from "./decision";

/** `decide_approval` returns `_approval_out` plus `resumed` (router.py:359). */
type DecideResponse = Approval & { resumed: boolean };

/** The class of refusal, phrased with this screen's words — the title names the
 *  rule (missing permission, unreachable server, refused decision), never a code. */
function refusalTitle(refusal: DecisionRefusal): string {
  switch (refusal.kind) {
    case "permission":
      return ap.permissionTitle;
    case "network":
      return ap.networkTitle;
    case "server":
      return ap.serverTitle;
    default:
      return ap.refusedTitle;
  }
}

export function ApprovalDecisionDialog({
  approval,
  decision,
  open,
  onOpenChange,
}: {
  approval: Approval;
  decision: Decision;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const isDeny = decision === DENY;
  const [reason, setReason] = React.useState("");
  const [refusal, setRefusal] = React.useState<DecisionRefusal | null>(null);
  const queryClient = useQueryClient();
  const { draftKey, clearKey, spendKey, spent } = useDialogIdempotencyKey(open);

  // A fresh target (or a flipped approve/deny) is a fresh draft: clear the typed
  // reason and any prior refusal so the dialog never carries a decision across.
  React.useEffect(() => {
    if (open) {
      setReason("");
      setRefusal(null);
    }
  }, [open, approval.id, decision]);

  const built = buildDecisionPayload({ decision, reason });
  const reasonTooLong = !built.ok && built.error === "reason_too_long";

  const decide = useMutation<ApiResponse<DecideResponse>, Error, DecisionPayload>({
    mutationFn: (body) =>
      apiWithMeta<DecideResponse>(`/ai/approvals/${approval.id}/decide`, {
        method: "POST",
        body,
        idempotencyKey: draftKey(),
      }),
    onSuccess: (res) => {
      clearKey();
      setRefusal(null);
      onOpenChange(false);
      // The row left PENDING and (on approve) may have been consumed by the
      // resumed run — every status list this screen can show is re-read, not
      // patched from the response.
      queryClient.invalidateQueries({ queryKey: qk.approvals("PENDING") });
      queryClient.invalidateQueries({ queryKey: qk.approvals("APPROVED") });
      queryClient.invalidateQueries({ queryKey: qk.approvals("REJECTED") });
      toast({
        title: isDeny ? ap.denyDone : ap.approveDone,
        description: res.data.resumed ? ap.resumedNote : undefined,
        variant: isDeny ? "default" : "success",
      });
    },
    onError: (err) => {
      const next = classifyDecisionError(err);
      setRefusal(next);
      // Terminal (409/412, or this route's "already decided / expired / gone"
      // 400/404): the key is spent, stop submitting. A 403/400 that ran nothing
      // keeps the key and stays retryable.
      if (next.terminal) spendKey();
    },
  });

  function submit() {
    if (spent || !built.ok) return;
    setRefusal(null);
    decide.mutate(built.body);
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (decide.isPending ? undefined : onOpenChange(next))}>
      <DialogContent data-testid="decision-dialog" className="max-w-md">
        <DialogHeader>
          <DialogTitle>{isDeny ? ap.denyTitle : ap.approveTitle}</DialogTitle>
          <DialogDescription>{isDeny ? ap.denyBody : ap.approveBody}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* The action being decided, shown so the confirmation names what it
              releases rather than a bare "are you sure". */}
          <p className="text-[13px] text-muted-foreground" data-testid="decision-action">
            {approval.action}
          </p>

          {isDeny && (
            <div>
              <Label htmlFor="decision-reason">{ap.reasonLabel}</Label>
              <Textarea
                id="decision-reason"
                data-testid="decision-reason"
                rows={3}
                autoComplete="off"
                aria-invalid={reasonTooLong}
                aria-describedby="decision-reason-hint"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                disabled={decide.isPending || spent}
              />
              <p id="decision-reason-hint" className="mt-1 text-[11px] text-muted-foreground">
                {ap.reasonHint} · {DECISION_REASON_MAX}
              </p>
              {reasonTooLong && (
                <p role="alert" data-testid="decision-reason-error" className="mt-1 text-[12px] text-danger">
                  {ap.reasonTooLong}
                </p>
              )}
            </div>
          )}

          {refusal && (
            <div className="space-y-2">
              <div
                role="alert"
                aria-live="assertive"
                data-testid="decision-refused"
                className="rounded-lg border border-danger/40 bg-danger-soft p-3 text-[12px]"
              >
                <strong className="block text-danger">{refusalTitle(refusal)}</strong>
                {/* The message is the backend's sentence — LTR, so an English
                    status line inside an RTL layout reads exactly as written. */}
                <p dir="ltr" className="mt-1 break-words text-foreground/90">
                  {refusal.message || "—"}
                </p>
                {!refusal.terminal && <p className="mt-1 text-muted-foreground">{ap.refusedHint}</p>}
              </div>
              {refusal.terminal && (
                <div
                  role="alert"
                  aria-live="assertive"
                  data-testid="decision-terminal"
                  className="rounded-lg border border-danger/40 bg-danger-soft p-3 text-[12px]"
                >
                  <strong className="block text-danger">{ap.terminalTitle}</strong>
                  <p className="mt-1 text-muted-foreground">{ap.terminalBody}</p>
                  <Button className="mt-2" size="sm" variant="outline" onClick={() => onOpenChange(false)}>
                    {ap.terminalAction}
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>

        <DialogFooter className="items-center gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)} data-testid="decision-cancel">
            {ap.cancel}
          </Button>
          <Button
            variant={isDeny ? "destructive" : "default"}
            onClick={submit}
            disabled={decide.isPending || spent || !built.ok}
            data-testid="decision-submit"
          >
            {isDeny ? ap.denySubmit : ap.approveSubmit}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
