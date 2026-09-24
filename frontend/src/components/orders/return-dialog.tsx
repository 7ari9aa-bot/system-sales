"use client";

/** Return a shipped/delivered order — `POST /orders/{id}/return`.
 *
 *  ADR-052: the return is a two-step saga (restock, then close the order), and
 *  MONEY IS NOT ONE OF ITS STEPS. A merchant who hits "return" expecting the
 *  customer's money back has to be told, on this form, that the refund is a
 *  separate action on a payment — otherwise the screen quietly promises a refund
 *  the process will never make.
 *
 *  `reason` is a CLOSED vocabulary: `returns.RETURN_REASONS` = the two values
 *  below, and `process_return` raises `ValidationError("unknown return reason")`
 *  for anything else. So this is a select of exactly those two, never a free-text
 *  box: the server's list is the source of the options, in its own order.
 *
 *  One Idempotency-Key per open. A replayed key answering 409 freezes the dialog
 *  for the same reason as a refund: the restock may already have happened, and a
 *  second one under a fresh key would put stock on the shelf that did not come
 *  back.
 */

import * as React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiWithMeta, type ApiResponse } from "@/lib/api";
import { invalidateOrderReads } from "@/lib/queries";
import { toast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Label, Select } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ot } from "./labels";
import {
  DEFAULT_RETURN_REASON,
  RETURN_REASONS,
  buildReturnBody,
  classifyWriteError,
  type ReturnReason,
  type WriteRefusal,
} from "./order-ops";
import { WriteOutcome, useDialogIdempotencyKey } from "./order-write-ui";

/** `router.return_order` — which saga answered, and where the order ended. */
type ReturnResponse = { ok: boolean; saga_id: string; saga_status: string; order_status: string };

function reasonLabel(reason: ReturnReason): string {
  return reason === "delivery_failed" ? ot.returnReasonDelivery : ot.returnReasonCustomer;
}

export function ReturnDialog({
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
  const [reason, setReason] = React.useState<ReturnReason>(DEFAULT_RETURN_REASON);
  const [refusal, setRefusal] = React.useState<WriteRefusal | null>(null);
  const queryClient = useQueryClient();
  const { draftKey, clearKey, spendKey, spent } = useDialogIdempotencyKey(open);

  const ret = useMutation<ApiResponse<ReturnResponse>, Error, void>({
    mutationFn: () =>
      apiWithMeta<ReturnResponse>(`/orders/${orderId}/return`, {
        method: "POST",
        body: buildReturnBody(reason),
        idempotencyKey: draftKey(),
      }),
    onSuccess: (res) => {
      clearKey();
      setReason(DEFAULT_RETURN_REASON);
      setRefusal(null);
      onOpenChange(false);
      invalidateOrderReads(queryClient, orderId);
      // `saga_status` is reported, not smoothed over: a saga that stopped
      // halfway is a different fact from one that completed, and the goods and
      // the lifecycle can legitimately disagree until a human fixes it.
      toast({
        title: ot.returnDoneTitle,
        description: `${ot.returnSaga(res.data.saga_status)} · #${orderNumber}`,
        variant: res.data.saga_status === "completed" ? "success" : "warning",
      });
    },
    onError: (err) => {
      const next = classifyWriteError(err);
      setRefusal(next);
      if (next.kind === "conflict" || next.kind === "stale") spendKey();
    },
  });

  function submit() {
    if (spent) return;
    setRefusal(null);
    ret.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="return-dialog">
        <DialogHeader>
          <DialogTitle>{ot.returnTitle}</DialogTitle>
          <DialogDescription>{ot.returnDescription}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <p
            data-testid="return-money-note"
            className="rounded-lg border border-border bg-muted p-3 text-[12px] text-muted-foreground"
          >
            {ot.returnMoneyNote}
          </p>

          <div>
            <Label htmlFor="return-reason">{ot.returnReasonLabel}</Label>
            {/* The two reasons the process knows, and no third escape hatch. */}
            <Select
              id="return-reason"
              data-testid="return-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value as ReturnReason)}
            >
              {RETURN_REASONS.map((option) => (
                <option key={option} value={option}>
                  {reasonLabel(option)}
                </option>
              ))}
            </Select>
          </div>

          <WriteOutcome testid="return" refusal={refusal} onClose={() => onOpenChange(false)} />
        </div>

        <DialogFooter className="items-center gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {ot.cancelAction}
          </Button>
          <Button onClick={submit} disabled={ret.isPending || spent} data-testid="submit-return">
            {ot.returnSubmit}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
