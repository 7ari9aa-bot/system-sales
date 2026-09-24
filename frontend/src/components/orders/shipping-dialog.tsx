"use client";

/** Correct where an open order is going — `PATCH /orders/{id}/shipping`, versioned.
 *
 *  Three rules this form exists to honor:
 *
 *  1. It is a CONDITIONAL write. `apply_versioned_update` runs the UPDATE with the
 *     expected version in its WHERE clause, so a stale `If-Match` answers 409 (and
 *     a bare If-Match that cannot parse is a 400). The version comes from the
 *     detail read's own body/ETag, and a lost write means RE-READ — never "force
 *     it", because forcing overwrites a correction another staffer just made.
 *     Hence: a 409/412 blocks the submit until the merchant presses "re-read".
 *  2. There is NO Idempotency-Key here, on purpose. `service.update_shipping`
 *     says the retry control is the compare-and-set, not a key: the version IS
 *     the answer to "did this already happen". The row is also at its latest
 *     version after a successful PATCH, so the next attempt from this screen
 *     cannot silently replay an old write.
 *  3. Only touched fields go out, and an address is sent WHOLE.
 *     `update_shipping` replaces `shipping_address` rather than merging into it,
 *     so a partial object would delete the parts the form never showed; and both
 *     fields absent is the 400 the service raises itself ("nothing to change"),
 *     which is refused here instead.
 *
 *  The stored address is not on `GET /orders/{id}`, so the box starts empty and
 *  says so: a merchant correcting a typo re-states the address they can read in
 *  the customer's record. Guessing a partial one would be the worse failure.
 */

import * as React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RotateCw } from "lucide-react";
import { apiWithMeta, type ApiResponse } from "@/lib/api";
import { invalidateOrderReads, qk } from "@/lib/queries";
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
import { buildShippingPayload, classifyWriteError, type ShippingError, type ShippingPatch, type WriteRefusal } from "./order-ops";
import { RefusalNotice } from "./order-write-ui";

/** `router.update_shipping` — and the new version the NEXT write must send. */
type ShippingResponse = {
  id: string;
  number: string;
  status: string;
  version: number;
  shipping_address: Record<string, unknown> | null;
  shipping_method: string | null;
};

function shippingErrorText(error: ShippingError): string {
  if (error === "invalid_json") return ot.shippingInvalidJson;
  if (error === "not_an_object") return ot.shippingNotObject;
  if (error === "method_too_long") return ot.shippingMethodTooLong;
  return ot.shippingNothing;
}

export function ShippingDialog({
  open,
  onOpenChange,
  orderId,
  version,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orderId: string;
  /** The version the detail read answered with — the token this write claims. */
  version: number;
}) {
  const [method, setMethod] = React.useState("");
  const [address, setAddress] = React.useState("");
  const [refusal, setRefusal] = React.useState<WriteRefusal | null>(null);
  /** A lost conditional write, held separately from the dialog's draft: the form
   *  keeps what the merchant typed while the record underneath it is re-read. */
  const [stale, setStale] = React.useState<string | null>(null);
  const queryClient = useQueryClient();

  // A new open is a new read of the row: nothing carried over from a lost race.
  React.useEffect(() => {
    if (!open) return;
    setStale(null);
    setRefusal(null);
  }, [open]);

  const built = buildShippingPayload({ method, address });
  const showError = built.error !== null;

  const patch = useMutation<ApiResponse<ShippingResponse>, Error, ShippingPatch>({
    mutationFn: (body) =>
      apiWithMeta<ShippingResponse>(`/orders/${orderId}/shipping`, {
        method: "PATCH",
        body,
        ifMatch: version,
      }),
    onSuccess: (res) => {
      setMethod("");
      setAddress("");
      setRefusal(null);
      setStale(null);
      onOpenChange(false);
      // The row's version moved (or did not, for a no-op PATCH — the service
      // claims nothing it did not change). Either way the screen's copy is
      // re-read, so the next correction states a version the server agrees with.
      invalidateOrderReads(queryClient, orderId);
      toast({
        title: ot.shippingDoneTitle,
        description: `${ot.shippingVersion(res.data.version)} — ${ot.shippingDoneHint}`,
        variant: "success",
      });
    },
    onError: (err) => {
      const next = classifyWriteError(err);
      if (next.kind === "conflict" || next.kind === "stale") {
        // Re-read, do not overwrite. The draft stays; the version does not.
        setStale(next.message);
        return;
      }
      setRefusal(next);
    },
  });

  function submit() {
    if (stale !== null || built.error !== null) return;
    setRefusal(null);
    patch.mutate(built.body);
  }

  /** Drop the stale claim by going back to the server for the current version.
   *  The draft survives; the version is whatever the fresh read answers with. */
  function reread() {
    setStale(null);
    void queryClient.invalidateQueries({ queryKey: qk.order(orderId) });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="shipping-dialog">
        <DialogHeader>
          <DialogTitle>{ot.shippingTitle}</DialogTitle>
          <DialogDescription>{ot.shippingDescription}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <p dir="ltr" className="text-[11px] text-muted-foreground" data-testid="shipping-version">
            {ot.shippingVersion(version)}
          </p>

          <div>
            <Label htmlFor="shipping-method">{ot.shippingMethodLabel}</Label>
            <Input
              id="shipping-method"
              data-testid="shipping-method"
              type="text"
              dir="ltr"
              autoComplete="off"
              aria-describedby="shipping-method-hint"
              aria-invalid={built.error === "method_too_long"}
              value={method}
              onChange={(e) => setMethod(e.target.value)}
            />
            <p id="shipping-method-hint" className="mt-1 text-[11px] text-muted-foreground">
              {ot.shippingMethodHint}
            </p>
          </div>

          <div>
            <Label htmlFor="shipping-address">{ot.shippingAddressLabel}</Label>
            <Input
              id="shipping-address"
              data-testid="shipping-address"
              type="text"
              dir="ltr"
              autoComplete="off"
              aria-describedby="shipping-address-hint"
              aria-invalid={built.error === "invalid_json" || built.error === "not_an_object"}
              value={address}
              onChange={(e) => setAddress(e.target.value)}
            />
            <p id="shipping-address-hint" className="mt-1 text-[11px] text-muted-foreground">
              {ot.shippingAddressHint}
            </p>
          </div>

          {showError && built.error !== null && (
            <p role="alert" data-testid="shipping-error" className="text-[12px] text-danger">
              {shippingErrorText(built.error)}
            </p>
          )}

          {stale !== null && (
            <div
              role="alert"
              aria-live="assertive"
              data-testid="shipping-stale"
              className="rounded-lg border border-danger/40 bg-danger-soft p-3 text-[12px]"
            >
              <strong className="block text-danger">{ot.shippingStaleTitle}</strong>
              <p dir="ltr" className="mt-1 break-words text-foreground/90">
                {stale || "—"}
              </p>
              <Button variant="outline" size="sm" className="mt-2" onClick={reread} data-testid="shipping-reread">
                <RotateCw aria-hidden="true" />
                {ot.shippingReread}
              </Button>
            </div>
          )}

          {refusal && <RefusalNotice testid="shipping-refused" refusal={refusal} />}
        </div>

        <DialogFooter className="items-center gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {ot.cancelAction}
          </Button>
          <Button
            onClick={submit}
            disabled={patch.isPending || stale !== null || showError}
            data-testid="submit-shipping"
          >
            {ot.shippingSubmit}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
