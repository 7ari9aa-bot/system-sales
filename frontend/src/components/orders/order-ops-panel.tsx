"use client";

/** The order record's operations surface: the two ledgers, and the four writes.
 *
 *  `payments` and `status-history` are SEPARATE queries with separate loading,
 *  empty and error states (§113). That separation is not decoration:
 *  `GET /orders/{id}` answers the money position, `GET /orders/{id}/payments`
 *  answers what a refund may target, and `GET /orders/{id}/status-history`
 *  answers why the order is where it is. When one of them is down, the others
 *  must stay on screen and the actions that depend on the dead one must
 *  disappear — a refund button next to an unreadable ledger is a guess.
 *
 *  Which action is offered is the server's state machine, not this file's
 *  opinion: `canCancel` mirrors `TRANSITIONS`' edges into `cancelled`,
 *  `canEditShipping` mirrors `_SHIPPING_EDITABLE_STATUSES`, `canReturn` mirrors
 *  `RETURNABLE_STATUSES`, and a refund button appears only on a payment
 *  `register_refund` would accept. The write still answers 409/400 if the row
 *  moved since this read — the gate is courtesy, the service is the authority.
 *
 *  There is NO client-side permission model to consult: `require_permission
 *  ("orders:write")` runs on the server, so an action the signed-in staff cannot
 *  take is discovered on the click, and the 403's own sentence is what the dialog
 *  shows (`RefusalNotice`) — with the submit still enabled, because nothing ran.
 */

import * as React from "react";
import { Ban, CreditCard, History, RotateCcw, Truck, Undo2 } from "lucide-react";
import { useOrderPayments, useOrderStatusHistory, type OrderDetail, type OrderPaymentRow } from "@/lib/queries";
import { t } from "@/lib/t";
import { getLang } from "@/lib/i18n";
import { formatMoney } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { ot } from "./labels";
import { canCancel, canEditShipping, canReturn, isRefundablePayment } from "./order-ops";
import { CancelOrderDialog } from "./cancel-order-dialog";
import { RefundDialog } from "./refund-dialog";
import { ReturnDialog } from "./return-dialog";
import { ShippingDialog } from "./shipping-dialog";

/* ------------------------------------------------------------ formatting -- */

/** Same locale rule as the other screens' local helper (customer drawer, my
 *  work, notifications): the dates follow the reading language, the numbers and
 *  the provider references stay `dir="ltr"` in the JSX above.
 *  A missing timestamp renders as a dash, never as `Invalid Date`. */
function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const locale = getLang() === "en" ? "en-GB" : "ar-EG";
  return new Date(value).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
}

const PAYMENT_VARIANT: Record<string, "warning" | "primary" | "success" | "danger" | "default"> = {
  pending: "warning",
  authorized: "warning",
  captured: "success",
  partially_refunded: "primary",
  refunded: "danger",
  failed: "danger",
};

function PaymentRow({ payment, onRefund }: { payment: OrderPaymentRow; onRefund: () => void }) {
  const refundable = isRefundablePayment(payment.status);
  return (
    <li
      data-testid={`order-payment-${payment.id}`}
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border p-3"
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          {/* The stored word is shown as the server writes it: a status is a
              vocabulary token, and translating it would hide what the backend
              answers on a refusal. */}
          <Badge variant={PAYMENT_VARIANT[payment.status] ?? "default"}>{payment.status}</Badge>
          <span className="text-[12px] text-muted-foreground">{payment.method}</span>
        </div>
        <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[12px] text-muted-foreground">
          <span>{ot.paymentProvider}:</span>
          <span dir="ltr">{payment.provider ?? "—"}</span>
          <span>{ot.paymentProviderRef}:</span>
          <span dir="ltr" data-testid="payment-provider-ref" className="break-all">
            {payment.provider_ref ?? "—"}
          </span>
          <span>{ot.paymentPaidAt}:</span>
          <span dir="ltr" data-testid="payment-paid-at">
            {payment.paid_at ? formatDateTime(payment.paid_at) : "—"}
          </span>
        </div>
        {!refundable && (
          <p className="mt-1 text-[11px] text-muted-foreground" data-testid={`payment-no-refund-${payment.id}`}>
            {ot.cannotRefund}
          </p>
        )}
      </div>

      <div className="flex items-center gap-3">
        <strong dir="ltr" className="text-[15px] font-bold" data-testid="payment-amount">
          {formatMoney(payment.amount, payment.currency)}
        </strong>
        {/* A refund is an action on a CAPTURE: `register_refund` refuses anything
            else, so the button is not offered rather than offered and refused. */}
        {refundable && (
          <Button variant="outline" size="sm" onClick={onRefund} data-testid={`refund-payment-${payment.id}`}>
            <Undo2 aria-hidden="true" />
            {ot.refundAction}
          </Button>
        )}
      </div>
    </li>
  );
}

export function OrderOpsPanel({ order }: { order: OrderDetail }) {
  const paymentsQuery = useOrderPayments(order.id);
  const historyQuery = useOrderStatusHistory(order.id);

  // `refunding` holds the payment the dialog is about: the cap, the currency and
  // the route all belong to THAT row, and a dialog that guessed them could price
  // a refund against the wrong capture.
  const [refundTarget, setRefundTarget] = React.useState<OrderPaymentRow | null>(null);
  const [cancelOpen, setCancelOpen] = React.useState(false);
  const [returnOpen, setReturnOpen] = React.useState(false);
  const [shippingOpen, setShippingOpen] = React.useState(false);

  const payments = paymentsQuery.data ?? [];
  const history = historyQuery.data ?? [];

  return (
    <div className="space-y-4">
      {/* ---------------------------------------------------- the payments -- */}
      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
          <CardTitle className="flex items-center gap-2 text-sm">
            <CreditCard aria-hidden="true" className="size-4 text-muted-foreground" />
            {ot.paymentsHeading}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {paymentsQuery.isError ? (
            /* A ledger that cannot be read is not an empty ledger, and the money
               actions are hidden with it: no refund may be offered against
               figures this screen cannot see. */
            <div data-testid="order-payments-error">
              <ErrorState
                message={paymentsQuery.error instanceof Error ? paymentsQuery.error.message : ot.paymentsUnavailable}
                onRetry={() => void paymentsQuery.refetch()}
              />
            </div>
          ) : paymentsQuery.isLoading ? (
            <div className="space-y-2" aria-busy="true" aria-label={t.loading}>
              {Array.from({ length: 2 }).map((_, i) => (
                <div key={i} className="h-16 animate-pulse rounded-lg bg-muted" />
              ))}
            </div>
          ) : payments.length === 0 ? (
            <EmptyState
              icon={<CreditCard aria-hidden="true" />}
              title={ot.paymentsEmpty}
              description={ot.paymentsEmptyHint}
              testid="order-payments-empty"
              className="py-8"
            />
          ) : (
            <ul className="space-y-2" data-testid="order-payments-list">
              {payments.map((payment) => (
                <PaymentRow
                  key={payment.id}
                  payment={payment}
                  onRefund={() => setRefundTarget(payment)}
                />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* --------------------------------------------------------- history -- */}
      <Card>
        <CardHeader className="space-y-0">
          <CardTitle className="flex items-center gap-2 text-sm">
            <History aria-hidden="true" className="size-4 text-muted-foreground" />
            {ot.historyHeading}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {historyQuery.isError ? (
            <div data-testid="order-history-error">
              <ErrorState
                message={historyQuery.error instanceof Error ? historyQuery.error.message : ot.historyUnavailable}
                onRetry={() => void historyQuery.refetch()}
              />
            </div>
          ) : historyQuery.isLoading ? (
            <div className="space-y-2" aria-busy="true" aria-label={t.loading}>
              {Array.from({ length: 2 }).map((_, i) => (
                <div key={i} className="h-10 animate-pulse rounded-lg bg-muted" />
              ))}
            </div>
          ) : history.length === 0 ? (
            <EmptyState
              icon={<History aria-hidden="true" />}
              title={ot.historyEmpty}
              testid="order-history-empty"
              className="py-8"
            />
          ) : (
            <ol className="space-y-2" data-testid="order-history-list">
              {history.map((entry) => (
                <li
                  key={entry.id}
                  data-testid={`order-history-${entry.id}`}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-border p-2 text-[12px]"
                >
                  <span className="flex items-center gap-1">
                    <span className="text-muted-foreground">{ot.historyFrom}:</span>
                    {/* `from_status` is null on an order's first entry, and null
                        is a dash — never the empty string, never the word null. */}
                    <span dir="ltr" data-testid="history-from">
                      {entry.from_status ?? "—"}
                    </span>
                  </span>
                  <span aria-hidden="true">←</span>
                  <span dir="ltr" data-testid="history-to">
                    {entry.to_status}
                  </span>
                  <span className="min-w-0 flex-1 truncate">
                    <span className="text-muted-foreground">{ot.historyNote}: </span>
                    <span data-testid="history-note">{entry.note ?? "—"}</span>
                  </span>
                  <span dir="ltr" className="text-muted-foreground" data-testid="history-when">
                    {formatDateTime(entry.created_at)}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>

      {/* ------------------------------------------------------- the writes -- */}
      <Card>
        <CardHeader className="space-y-0">
          <CardTitle className="text-sm">{ot.operations}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {canCancel(order.status) && (
            <Button variant="outline" size="sm" onClick={() => setCancelOpen(true)} data-testid="cancel-order-btn">
              <Ban aria-hidden="true" />
              {ot.cancelBtn}
            </Button>
          )}
          {canEditShipping(order.status) && (
            <Button variant="outline" size="sm" onClick={() => setShippingOpen(true)} data-testid="shipping-btn">
              <Truck aria-hidden="true" />
              {ot.shippingBtn}
            </Button>
          )}
          {canReturn(order.status) && (
            <Button variant="outline" size="sm" onClick={() => setReturnOpen(true)} data-testid="return-order-btn">
              <RotateCcw aria-hidden="true" />
              {ot.returnBtn}
            </Button>
          )}
        </CardContent>
      </Card>

      {refundTarget && (
        <RefundDialog
          open={refundTarget !== null}
          onOpenChange={(next) => {
            if (!next) setRefundTarget(null);
          }}
          orderId={order.id}
          payment={refundTarget}
        />
      )}
      <CancelOrderDialog
        open={cancelOpen}
        onOpenChange={setCancelOpen}
        orderId={order.id}
        orderNumber={order.number}
      />
      <ReturnDialog
        open={returnOpen}
        onOpenChange={setReturnOpen}
        orderId={order.id}
        orderNumber={order.number}
      />
      {/* `order.version` is LIVE: the panel re-renders from the detail query after
          every write, so the dialog can never send a version the server has
          already moved past. */}
      <ShippingDialog
        open={shippingOpen}
        onOpenChange={setShippingOpen}
        orderId={order.id}
        version={order.version}
      />
    </div>
  );
}
