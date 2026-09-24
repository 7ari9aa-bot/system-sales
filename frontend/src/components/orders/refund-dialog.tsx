"use client";

/** Refund one captured payment — `POST /orders/{id}/payments/{pid}/refunds`.
 *
 *  The money rules, in the order the server applies them:
 *  * `RefundCreateRequest.amount` is `Decimal, gt=0`, so the draft is parsed on
 *    `bigint` minor units and re-rendered as a STRING (`{amount: "25.00"}`). A
 *    JSON number would have crossed float64 on the way out.
 *  * `register_refund` only accepts a `captured` or `partially_refunded` payment,
 *    and refuses anything past the capture. The cap this dialog can state is the
 *    payment's own `amount` when the status is a clean `captured`; a partially
 *    refunded capture has an UNKNOWN remainder (the refund ledger is not part of
 *    the payment read), so the dialog says it cannot compute one and lets the
 *    server's 409 speak — inventing a number here would block a legal refund.
 *  * `reason` is optional and capped at 512, so a blank one is absent from the
 *    body rather than `""`.
 *
 *  One Idempotency-Key per OPENED dialog (`useDialogIdempotencyKey`): a retry, a
 *  re-click and a refresh-then-replay all carry it, a 4xx keeps it, and a 409
 *  freezes the submit instead of minting a new one — a second key here could give
 *  the same money back twice.
 */

import * as React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiWithMeta, type ApiResponse } from "@/lib/api";
import { invalidateOrderReads, type OrderPaymentRow } from "@/lib/queries";
import { formatMoney } from "@/lib/utils";
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
import { STORAGE_SCALE, inputScale, renderMinor } from "./money";
import {
  REFUND_REASON_MAX,
  buildRefundPayload,
  classifyWriteError,
  refundCapMinor,
  type RefundError,
  type RefundPayload,
  type WriteRefusal,
} from "./order-ops";
import { WriteOutcome, useDialogIdempotencyKey } from "./order-write-ui";

/** `router.create_refund` → 201. `status` is the refund's own state, not the
 *  order's; the order's money position is re-read, never inferred from here. */
type RefundResponse = { id: string; status: string; amount: string };

/** The refusal, phrased. `over_captured` names the ceiling it broke, because
 *  "invalid" would be a shrug where the merchant needs the number. */
function refundErrorText(error: RefundError, scale: number, capMinor: bigint | null, currency: string | null): string {
  switch (error) {
    case "empty":
      return ot.refundAmountEmpty;
    case "zero":
      return ot.refundAmountZero;
    case "over_captured":
      return ot.refundOverCaptured(
        capMinor === null ? "—" : formatMoney(renderMinor(capMinor, STORAGE_SCALE), currency),
      );
    case "reason_too_long":
      return ot.refundReasonTooLong;
    case "negative":
      return ot.negative;
    case "too_large":
      return ot.too_large;
    case "too_precise":
      return ot.too_precise(scale);
    default:
      return ot.not_a_number;
  }
}

export function RefundDialog({
  open,
  onOpenChange,
  orderId,
  payment,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orderId: string;
  payment: OrderPaymentRow;
}) {
  const [amount, setAmount] = React.useState("");
  const [reason, setReason] = React.useState("");
  const [refusal, setRefusal] = React.useState<WriteRefusal | null>(null);
  const queryClient = useQueryClient();
  const { draftKey, clearKey, spendKey, spent } = useDialogIdempotencyKey(open);

  // §47: the code is the payment's own, and the exponent it carries decides what
  // may be typed. An unlisted code falls back to 2, like `money.py:_exponent_for`.
  const scale = inputScale(payment.currency);
  const capMinor = refundCapMinor(payment);

  const draft = { amount, reason };
  const built = buildRefundPayload(draft, { scale, capMinor });
  /** Nothing typed yet is not a mistake: the box starts empty and the submit is
   *  simply disabled. The message appears once the text is wrong. */
  const showError = amount.trim() !== "" && !built.ok;

  const refund = useMutation<ApiResponse<RefundResponse>, Error, RefundPayload>({
    mutationFn: (body) =>
      apiWithMeta<RefundResponse>(`/orders/${orderId}/payments/${payment.id}/refunds`, {
        method: "POST",
        body,
        idempotencyKey: draftKey(),
      }),
    onSuccess: (res) => {
      clearKey();
      setAmount("");
      setReason("");
      setRefusal(null);
      onOpenChange(false);
      // The ledger moved: the money position, the payment's status and the
      // history entry are all re-read rather than patched from this response.
      invalidateOrderReads(queryClient, orderId);
      toast({
        title: ot.refundDoneTitle,
        description: res.replayed
          ? `${ot.alreadyCreatedHint} — ${formatMoney(res.data.amount, payment.currency)}`
          : `${ot.refundDoneHint} — ${formatMoney(res.data.amount, payment.currency)}`,
        variant: "success",
      });
    },
    onError: (err) => {
      const next = classifyWriteError(err);
      setRefusal(next);
      // A 4xx (other than 409) RELEASED the key server-side, so the corrected
      // draft may go out under it again. A 409/412 spent it: keep it, stop.
      if (next.kind === "conflict" || next.kind === "stale") spendKey();
    },
  });

  function submit() {
    if (spent || !built.ok) return;
    setRefusal(null);
    refund.mutate(built.body);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="refund-dialog">
        <DialogHeader>
          <DialogTitle>{ot.refundTitle}</DialogTitle>
          <DialogDescription>{ot.refundDescription}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            {capMinor === null ? (
              <p data-testid="refund-cap-unknown" className="text-[12px] text-muted-foreground">
                {ot.refundCapUnknown}
              </p>
            ) : (
              <p data-testid="refund-captured" className="text-[12px] text-muted-foreground">
                {ot.refundCaptured(
                  formatMoney(renderMinor(capMinor, STORAGE_SCALE), payment.currency),
                )}
              </p>
            )}
            <Label htmlFor="refund-amount" className="mt-2">
              {ot.refundAmountLabel}
            </Label>
            <Input
              id="refund-amount"
              data-testid="refund-amount"
              /* type=text on purpose: a number input silently eats the "-" and
                 the third decimal this form exists to REPORT. */
              type="text"
              inputMode="decimal"
              dir="ltr"
              autoComplete="off"
              placeholder="0.00"
              aria-invalid={showError}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
            {showError && !built.ok && (
              <p role="alert" data-testid="refund-error" className="mt-1 text-[12px] text-danger">
                {refundErrorText(built.error, scale, capMinor, payment.currency)}
              </p>
            )}
          </div>

          <div>
            <Label htmlFor="refund-reason">{ot.refundReasonLabel}</Label>
            <Input
              id="refund-reason"
              data-testid="refund-reason"
              type="text"
              autoComplete="off"
              aria-describedby="refund-reason-hint"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <p id="refund-reason-hint" className="mt-1 text-[11px] text-muted-foreground">
              {ot.refundReasonHint} · {REFUND_REASON_MAX}
            </p>
          </div>

          <WriteOutcome testid="refund" refusal={refusal} onClose={() => onOpenChange(false)} />
        </div>

        <DialogFooter className="items-center gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)} data-testid="refund-cancel">
            {ot.cancelAction}
          </Button>
          <Button
            variant="destructive"
            onClick={submit}
            disabled={refund.isPending || spent || !built.ok}
            data-testid="submit-refund"
          >
            {ot.refundSubmit}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
