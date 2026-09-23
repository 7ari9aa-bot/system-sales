"use client";

/** The create-order dialog, with the money the server already accepts.
 *
 *  Three things live here that the old inline dialog lacked:
 *
 *  1. Discount / shipping / tax inputs, validated against the rules the backend
 *     enforces (`CreateOrderRequest` allows `ge=0` only; `money.py` refuses a
 *     negative term, refuses a negative grand total, and stores at two places),
 *     sent ONLY for the fields the merchant typed — an untouched form posts
 *     exactly the body this screen posted before these inputs existed.
 *  2. A running total computed on minor units (`./money.ts`), never on floats,
 *     labelled and rendered in the tenant's own currency from
 *     `useTenantCurrency`.
 *  3. One Idempotency-Key per OPENED dialog. The key is minted when the dialog
 *     opens and survives every submit, retry and re-click inside it, so a
 *     double-click replays the first answer instead of creating a second order.
 *     A 409 stops the dialog: resending under a fresh key would be a second
 *     create, and that is exactly the money bug the guard exists to stop.
 */

import * as React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { apiWithMeta, isConflictError, newIdempotencyKey, type ApiResponse } from "@/lib/api";
import {
  qk,
  useCancelOrder,
  useProducts,
  useTenantCurrency,
  type Customer,
} from "@/lib/queries";
import { t } from "@/lib/t";
import { formatMoney } from "@/lib/utils";
import { toast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Input, Label, Select } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ot } from "./labels";
import { STORAGE_SCALE, inputScale, renderMinor, type MoneyRejection } from "./money";
import {
  MONEY_FIELDS,
  buildCreateOrderPayload,
  summarizeOrderMoney,
  type CreateOrderPayload,
  type CreateOrderResponse,
  type MoneyDraft,
  type MoneyField,
  type OrderLine,
} from "./order-request";

const EMPTY_MONEY: MoneyDraft = { discount: "", shipping: "", tax: "" };
const ONE_LINE: OrderLine[] = [{ variant_id: "", quantity: 1 }];

/** Field names are read through the language proxy AT RENDER TIME — a
 *  module-level `ot.discount` would pin whichever language was active when this
 *  file was first imported. */
function fieldLabel(field: MoneyField): string {
  if (field === "discount") return ot.discount;
  if (field === "shipping") return ot.shipping;
  return ot.tax;
}

/** The sign the term carries in `subtotal - discount + shipping + tax`. */
function fieldSign(field: MoneyField): string {
  return field === "discount" ? "−" : "+";
}

/** The rejection reasons, phrased. `too_precise` names the tenant's own limit
 *  so the message is a rule, not a shrug. */
function moneyError(reason: MoneyRejection, scale: number): string {
  if (reason === "negative") return ot.negative;
  if (reason === "not_a_number") return ot.not_a_number;
  if (reason === "too_large") return ot.too_large;
  return ot.too_precise(scale);
}

export function CreateOrderDialog({
  open,
  onOpenChange,
  customers,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  customers: Customer[];
}) {
  const [customerId, setCustomerId] = React.useState("");
  const [lines, setLines] = React.useState<OrderLine[]>(ONE_LINE);
  const [money, setMoney] = React.useState<MoneyDraft>(EMPTY_MONEY);
  /** Non-null while a 409 stands: the write is over and the dialog waits for a
   *  human to look at the orders list. Holds the server's own message. */
  const [conflict, setConflict] = React.useState<string | null>(null);

  const productsQuery = useProducts();
  // §47: the currency is READ from the tenant, never assumed — it decides both
  // what a merchant may type (the ISO-4217 exponent) and what the totals are
  // labelled with. A failing read leaves `null`: the amount then renders without
  // a code and the exponent falls back to 2, exactly like `money.py:_exponent_for`.
  const currencyQuery = useTenantCurrency();
  const tenantCurrency = currencyQuery.data?.currency ?? null;
  const scale = inputScale(tenantCurrency);

  const cancelOrder = useCancelOrder();
  const queryClient = useQueryClient();

  // ONE key per opened dialog, not per click. Minted on the open transition;
  // `draftKey()` only ever reads it, so a retry, a re-click and a
  // refresh-then-replay all carry the same value. Cleared on success, so the
  // NEXT order (the next open) is a new intent with a new key.
  const keyRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!open) return;
    keyRef.current = newIdempotencyKey();
    setConflict(null);
  }, [open]);
  function draftKey(): string {
    if (keyRef.current === null) keyRef.current = newIdempotencyKey();
    return keyRef.current;
  }

  const variants = React.useMemo(
    () =>
      (productsQuery.data ?? []).flatMap((p) =>
        (p.variants ?? []).map((v) => ({
          ...v,
          label: `${p.title}${v.title ? ` — ${v.title}` : ""}${v.sku ? ` (${v.sku})` : ""}`,
        })),
      ),
    [productsQuery.data],
  );

  const chosen = React.useMemo(() => lines.filter((l) => l.variant_id !== ""), [lines]);

  // The figure the merchant sees, computed the way the server computes it.
  const summary = React.useMemo(
    () =>
      summarizeOrderMoney({
        lines: chosen,
        priceOf: (id) => variants.find((v) => v.id === id)?.price,
        money,
        scale,
      }),
    [chosen, variants, money, scale],
  );

  const create = useMutation<ApiResponse<CreateOrderResponse>, Error, CreateOrderPayload>({
    mutationFn: (payload) =>
      apiWithMeta<CreateOrderResponse>("/orders", {
        method: "POST",
        body: payload,
        idempotencyKey: draftKey(),
      }),
    onSuccess: (res) => {
      const created = res.data;
      keyRef.current = null;
      onOpenChange(false);
      setLines(ONE_LINE);
      setMoney(EMPTY_MONEY);
      setCustomerId("");
      setConflict(null);
      queryClient.invalidateQueries({ queryKey: qk.orders });
      queryClient.invalidateQueries({ queryKey: qk.dashboard });
      if (res.replayed) {
        // The guard answered with the FIRST response: nothing ran again. Say so
        // rather than confirming a creation that did not happen twice.
        toast({
          title: ot.alreadyCreatedTitle,
          description: `#${created.number} — ${ot.alreadyCreatedHint}`,
          variant: "warning",
        });
        return;
      }
      toast({
        title: t.orderCreated,
        description: `#${created.number}`,
        variant: "success",
        action: {
          label: t.undo,
          onClick: () => {
            // The API keys lifecycle actions by order id, not the human-facing
            // number; toasts + list invalidation live in useCancelOrder.
            cancelOrder.mutate(created.id);
          },
        },
      });
    },
    onError: (err) => {
      if (isConflictError(err)) {
        // 409 answers one of two questions and both need the same hands-off
        // reply: the key was already spent on a created order, or the draft
        // changed under it. Keep the key, keep the draft, stop submitting —
        // a new key here would re-run the create.
        setConflict(err.message);
        return;
      }
      toast({ title: t.somethingWentWrong, description: err.message, variant: "danger" });
    },
  });

  function submit() {
    if (conflict !== null) return;
    if (!customerId || chosen.length === 0 || !summary.valid) return;
    create.mutate(buildCreateOrderPayload({ customerId, lines: chosen, summary }));
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{t.createOrder}</DialogTitle>
          <DialogDescription>اختر العميل والأصناف — سيُسجَّل الطلب فورًا.</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <Label htmlFor="o-customer">{t.customer}</Label>
            <Select id="o-customer" value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
              <option value="">{t.chooseCustomer}</option>
              {customers.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} {c.phone ? `(${c.phone})` : ""}
                </option>
              ))}
            </Select>
          </div>

          <div className="space-y-2">
            <Label>{t.lineItems}</Label>
            {lines.map((line, index) => (
              <div key={index} className="flex items-end gap-2">
                <div className="flex-1">
                  <Select
                    aria-label={`${t.products} ${index + 1}`}
                    value={line.variant_id}
                    onChange={(e) =>
                      setLines(lines.map((l, i) => (i === index ? { ...l, variant_id: e.target.value } : l)))
                    }
                  >
                    <option value="">{t.chooseProduct}</option>
                    {variants.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.label} — {formatMoney(v.price, tenantCurrency)}
                      </option>
                    ))}
                  </Select>
                </div>
                <Input
                  type="number"
                  dir="ltr"
                  min={1}
                  aria-label={t.quantity}
                  className="w-20"
                  value={line.quantity}
                  onChange={(e) =>
                    setLines(
                      lines.map((l, i) =>
                        // A LINE COUNT, so an integer is the rule the server
                        // enforces (`_positive_int`): truncate before storing,
                        // never let "1.5" ride into the payload.
                        i === index ? { ...l, quantity: Math.max(1, Math.trunc(Number(e.target.value) || 1)) } : l,
                      ),
                    )
                  }
                />
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="حذف السطر"
                  onClick={() => setLines(lines.filter((_, i) => i !== index))}
                  disabled={lines.length === 1}
                >
                  <Trash2 aria-hidden="true" className="text-danger" />
                </Button>
              </div>
            ))}
            <Button variant="outline" size="sm" onClick={() => setLines([...lines, { variant_id: "", quantity: 1 }])}>
              {t.addLine}
            </Button>
          </div>

          {/* ---- the money terms the server has always accepted (§47) ---- */}
          <div className="space-y-2 border-t border-border pt-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <Label>{ot.moneyHeading}</Label>
              <span className="text-[11px] text-muted-foreground" data-testid="order-money-hint">
                {ot.moneyOptional}
              </span>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {MONEY_FIELDS.map((field: MoneyField) => {
                const state = summary.fields[field];
                const helpId = `o-money-help-${field}`;
                return (
                  <div key={field}>
                    <Label htmlFor={`o-money-${field}`}>{fieldLabel(field)}</Label>
                    <Input
                      id={`o-money-${field}`}
                      data-testid={`order-money-${field}`}
                      /* type=text on purpose: a number input silently drops the
                         "-" and the extra decimal this form exists to REPORT, so
                         the merchant would never learn why the server refuses
                         the value they meant to enter. */
                      type="text"
                      inputMode="decimal"
                      dir="ltr"
                      autoComplete="off"
                      placeholder="0.00"
                      aria-describedby={helpId}
                      aria-invalid={state.error !== null}
                      value={money[field]}
                      onChange={(e) => setMoney({ ...money, [field]: e.target.value })}
                    />
                    <p id={helpId} className="mt-1 text-[11px] leading-4">
                      {state.error !== null ? (
                        <span
                          role="alert"
                          data-testid={`order-money-error-${field}`}
                          className="text-danger"
                        >
                          {moneyError(state.error, scale)}
                        </span>
                      ) : (
                        <span className="text-muted-foreground" dir="ltr">
                          {tenantCurrency ?? ot.currencyUnknown}
                        </span>
                      )}
                    </p>
                  </div>
                );
              })}
            </div>
            {summary.negativeTotal && (
              <p role="alert" data-testid="order-discount-exceeds" className="text-[12px] text-danger">
                {ot.discountTooBig}
              </p>
            )}
            {summary.unpriced && chosen.length > 0 && (
              <p role="alert" data-testid="order-estimate-unreliable" className="text-[12px] text-danger">
                {ot.estimateUnreliable}
              </p>
            )}
          </div>
        </div>

        {conflict !== null && (
          <div
            role="alert"
            aria-live="assertive"
            data-testid="order-idempotency-conflict"
            className="rounded-lg border border-danger/40 bg-danger-soft p-3 text-[12px]"
          >
            <strong className="block text-danger">{ot.conflictTitle}</strong>
            <p className="mt-1 text-muted-foreground">{ot.conflictBody}</p>
            <p className="mt-1 text-muted-foreground" dir="ltr">
              {conflict}
            </p>
            <Button className="mt-2" size="sm" variant="outline" onClick={() => onOpenChange(false)}>
              {ot.conflictAction}
            </Button>
          </div>
        )}

        <DialogFooter className="items-center justify-between gap-3 sm:justify-between">
          <div className="space-y-0.5 text-[12px]" data-testid="order-totals">
            <div className="flex items-center gap-2 text-muted-foreground">
              <span>{ot.subtotal}</span>
              <strong dir="ltr">
                {formatMoney(renderMinor(summary.subtotal, STORAGE_SCALE), tenantCurrency)}
              </strong>
            </div>
            {MONEY_FIELDS.filter((f) => summary.fields[f].touched).map((f) => (
              <div key={f} className="flex items-center gap-2 text-muted-foreground">
                <span>{fieldLabel(f)}</span>
                <strong dir="ltr">
                  {fieldSign(f)}
                  {formatMoney(renderMinor(summary.fields[f].minor, STORAGE_SCALE), tenantCurrency)}
                </strong>
              </div>
            ))}
            <div className="flex items-center gap-2">
              <span>{ot.grandTotal}</span>
              <strong dir="ltr" data-testid="order-grand-total" title={ot.grandTotalHint}>
                {formatMoney(renderMinor(summary.grand, STORAGE_SCALE), tenantCurrency)}
              </strong>
            </div>
          </div>
          <Button
            onClick={submit}
            disabled={
              create.isPending ||
              conflict !== null ||
              !customerId ||
              chosen.length === 0 ||
              !summary.valid
            }
            data-testid="submit-order"
          >
            {t.createOrder}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
