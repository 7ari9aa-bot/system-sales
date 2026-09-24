"use client";

/** Cancel an open order — and record WHY, where the backend can actually keep it.
 *
 *  `POST /orders/{id}/cancel` takes NO body: FastAPI drops an undeclared field,
 *  so a reason sent there would silently vanish and the screen would claim a
 *  recorded cause that was never written. `POST /orders/{id}/status` is the route
 *  whose contract carries one (`StatusChangeRequest{status, note}`), it runs the
 *  same `_transition` path `cancel_order` runs — stock release included — and
 *  its note lands in `order_status_history`, which is where the record page then
 *  shows it. So this dialog posts `/status` with `status: "cancelled"`.
 *
 *  Two deliberate edges:
 *  * `note` is capped at 512 HERE. The request model declares no maximum, but
 *    `order_status_history.note` is `String(512)`, so a longer one is a database
 *    error rather than a 400 — this is the only place that can say so first.
 *  * The submit is the confirmation: an irreversible action needs an explicit
 *    acknowledgement, and an untouched note is ABSENT from the body rather than
 *    `""` (the column is nullable; an empty note reads as "a note was written").
 *
 *  One Idempotency-Key per open; a 409 freezes it, a 403 does not.
 */

import * as React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiWithMeta, type ApiResponse } from "@/lib/api";
import { invalidateOrderReads } from "@/lib/queries";
import { t } from "@/lib/t";
import { toast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ot } from "./labels";
import { CANCEL_NOTE_MAX, buildCancelBody, classifyWriteError, type WriteRefusal } from "./order-ops";
import { WriteOutcome, useDialogIdempotencyKey } from "./order-write-ui";

type StatusResponse = { ok: boolean };

export function CancelOrderDialog({
  open,
  onOpenChange,
  orderId,
  orderNumber,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orderId: string;
  orderNumber: string;
}) {
  const [note, setNote] = React.useState("");
  const [acked, setAcked] = React.useState(false);
  const [refusal, setRefusal] = React.useState<WriteRefusal | null>(null);
  const queryClient = useQueryClient();
  const { draftKey, clearKey, spendKey, spent } = useDialogIdempotencyKey(open);

  const trimmed = note.trim();
  const noteTooLong = trimmed.length > CANCEL_NOTE_MAX;

  const cancel = useMutation<ApiResponse<StatusResponse>, Error, void>({
    mutationFn: () =>
      apiWithMeta<StatusResponse>(`/orders/${orderId}/status`, {
        method: "POST",
        body: buildCancelBody(note),
        idempotencyKey: draftKey(),
      }),
    onSuccess: (res) => {
      clearKey();
      setNote("");
      setAcked(false);
      setRefusal(null);
      onOpenChange(false);
      // The status axis moved and a history row was written; both are re-read.
      invalidateOrderReads(queryClient, orderId);
      toast({
        title: t.orderCancelled,
        description: res.replayed ? ot.alreadyCreatedHint : `#${orderNumber} — ${ot.cancelDoneHint}`,
        variant: res.replayed ? "warning" : "success",
      });
    },
    onError: (err) => {
      const next = classifyWriteError(err);
      setRefusal(next);
      if (next.kind === "conflict" || next.kind === "stale") spendKey();
    },
  });

  function submit() {
    if (!acked || spent || noteTooLong) return;
    setRefusal(null);
    cancel.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="cancel-dialog">
        <DialogHeader>
          <DialogTitle>{ot.cancelTitle}</DialogTitle>
          <DialogDescription>{ot.cancelDescription}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <p
            role="alert"
            data-testid="cancel-warning"
            className="rounded-lg border border-warning/40 bg-warning-soft p-3 text-[12px] font-semibold text-warning"
          >
            {ot.cancelWarning}
          </p>

          <div>
            <Label htmlFor="cancel-note">{ot.cancelNoteLabel}</Label>
            <Input
              id="cancel-note"
              data-testid="cancel-note"
              type="text"
              autoComplete="off"
              aria-describedby="cancel-note-hint"
              aria-invalid={noteTooLong}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <p id="cancel-note-hint" className="mt-1 text-[11px] text-muted-foreground">
              {noteTooLong ? (
                <span role="alert" data-testid="cancel-note-too-long" className="text-danger">
                  {ot.cancelNoteTooLong}
                </span>
              ) : (
                ot.cancelNoteHint
              )}
            </p>
          </div>

          <label className="flex items-start gap-2 text-[13px]">
            <input
              type="checkbox"
              data-testid="cancel-confirm-ack"
              className="mt-0.5 size-4 accent-danger"
              checked={acked}
              onChange={(e) => setAcked(e.target.checked)}
            />
            <span>{ot.cancelAck}</span>
          </label>

          <WriteOutcome testid="cancel" refusal={refusal} onClose={() => onOpenChange(false)} />
        </div>

        <DialogFooter className="items-center gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {ot.cancelAction}
          </Button>
          <Button
            variant="destructive"
            onClick={submit}
            disabled={!acked || cancel.isPending || spent || noteTooLong}
            data-testid="submit-cancel"
          >
            {ot.cancelSubmit}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
