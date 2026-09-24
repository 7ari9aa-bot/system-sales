"use client";

/** The three things every order write shares, in one place.
 *
 *  1. `useDialogIdempotencyKey` — the §91 discipline, stated once instead of
 *     four times: ONE key per dialog OPEN (not per click), re-sent unchanged on
 *     every retry and across a 401→refresh (that part lives in `apiWithMeta`),
 *     cleared when the write succeeds, and NEVER re-minted after a 409/412. It
 *     now lives in `@/lib/use-dialog-idempotency` — a home with no order copy —
 *     so the approvals screen can reuse the discipline without dragging this
 *     file's vocabulary along; it is re-exported here so the order dialogs that
 *     import it from `./order-write-ui` are untouched.
 *  2. `<RefusalNotice>` — a refused action says WHY, in the backend's own
 *     sentence (`ApiError.message` is the envelope's `error.message`), with the
 *     status class deciding the title and the next step. A generic "something
 *     went wrong" is the failure this surface is built not to repeat.
 *  3. `<TerminalNotice>` — what a spent attempt means: the key stays, the
 *     submit stops, and a human re-reads the record.
 */

import * as React from "react";
import { Button } from "@/components/ui/button";
import { ot } from "./labels";
import { isTerminalRefusal, type WriteRefusal } from "./order-ops";

/** Re-exported so the guarded writes share one implementation — see above. */
export { useDialogIdempotencyKey } from "@/lib/use-dialog-idempotency";

/** The server's own words about a write it did not accept.
 *
 *  Rendered for EVERY failure, terminal or not, because a 409 carries a real
 *  reason too ("refund exceeds captured amount") and hiding it behind the freeze
 *  notice would leave the merchant guessing. The title names the class, not the
 *  status code, so it reads as a rule: missing permission, unreachable server,
 *  refused draft. */
export function RefusalNotice({ testid, refusal }: { testid: string; refusal: WriteRefusal }) {
  const terminal = isTerminalRefusal(refusal);
  const title =
    refusal.kind === "permission"
      ? ot.permissionTitle
      : refusal.kind === "network"
        ? ot.networkTitle
        : ot.refusedTitle;
  return (
    <div
      role="alert"
      aria-live="assertive"
      data-testid={testid}
      className="rounded-lg border border-danger/40 bg-danger-soft p-3 text-[12px]"
    >
      <strong className="block text-danger">{title}</strong>
      {/* The message is the backend's sentence — LTR, because it is English text
          inside an RTL layout and it must be readable exactly as written. */}
      <p dir="ltr" className="mt-1 break-words text-foreground/90">
        {refusal.message || "—"}
      </p>
      {!terminal && <p className="mt-1 text-muted-foreground">{ot.refusedHint}</p>}
    </div>
  );
}

/** A 409/412: the attempt is finished and this dialog will not fire it again. */
export function TerminalNotice({
  testid,
  refusal,
  onClose,
}: {
  testid: string;
  refusal: WriteRefusal;
  onClose: () => void;
}) {
  return (
    <div
      role="alert"
      aria-live="assertive"
      data-testid={testid}
      className="rounded-lg border border-danger/40 bg-danger-soft p-3 text-[12px]"
    >
      <strong className="block text-danger">{ot.terminalTitle}</strong>
      <p dir="ltr" className="mt-1 break-words text-foreground/90">
        {refusal.message || "—"}
      </p>
      <p className="mt-1 text-muted-foreground">{ot.terminalBody}</p>
      <Button className="mt-2" size="sm" variant="outline" onClick={onClose}>
        {ot.terminalAction}
      </Button>
    </div>
  );
}

/** Both notices, in the one order the dialogs need: the server's sentence first,
 *  the freeze on top of it once the attempt is terminal. */
export function WriteOutcome({
  testid,
  refusal,
  onClose,
}: {
  /** `<testid>-refused` and, when terminal, `<testid>-conflict`. */
  testid: string;
  refusal: WriteRefusal | null;
  onClose: () => void;
}) {
  if (!refusal) return null;
  return (
    <div className="space-y-2">
      <RefusalNotice testid={`${testid}-refused`} refusal={refusal} />
      {isTerminalRefusal(refusal) && (
        <TerminalNotice testid={`${testid}-conflict`} refusal={refusal} onClose={onClose} />
      )}
    </div>
  );
}
