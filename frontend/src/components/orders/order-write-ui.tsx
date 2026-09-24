"use client";

/** The three things every order write shares, in one place.
 *
 *  1. `useDialogIdempotencyKey` — the §91 discipline, stated once instead of
 *     four times: ONE key per dialog OPEN (not per click), re-sent unchanged on
 *     every retry and across a 401→refresh (that part lives in `apiWithMeta`),
 *     cleared when the write succeeds, and NEVER re-minted after a 409/412.
 *     `create-order-dialog.tsx` holds its own copy inline because it predates
 *     this file; the rule is identical.
 *  2. `<RefusalNotice>` — a refused action says WHY, in the backend's own
 *     sentence (`ApiError.message` is the envelope's `error.message`), with the
 *     status class deciding the title and the next step. A generic "something
 *     went wrong" is the failure this surface is built not to repeat.
 *  3. `<TerminalNotice>` — what a spent attempt means: the key stays, the
 *     submit stops, and a human re-reads the record.
 */

import * as React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { newIdempotencyKey } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ot } from "./labels";
import { isTerminalRefusal, type WriteRefusal } from "./order-ops";

/** One Idempotency-Key per opened dialog.
 *
 *  `spent` is set by a 409/412 and is what freezes the submit: the server said
 *  this attempt is over, and the only honest way to get a new key is to open the
 *  dialog again — a new intent. It resets on open, so a close-and-reopen is the
 *  one path to a fresh key, exactly as the guard expects. */
export function useDialogIdempotencyKey(open: boolean) {
  const keyRef = useRef<string | null>(null);
  const [spent, setSpent] = useState(false);

  useEffect(() => {
    if (!open) return;
    keyRef.current = newIdempotencyKey();
    setSpent(false);
  }, [open]);

  /** Read the key this dialog owns, minting one only if the open transition has
   *  not run yet (a submit cannot arrive before it, but never send no key). */
  const draftKey = useCallback((): string => {
    if (keyRef.current === null) keyRef.current = newIdempotencyKey();
    return keyRef.current;
  }, []);

  /** The write landed: the next dialog open is a new intent with a new key. */
  const clearKey = useCallback(() => {
    keyRef.current = null;
  }, []);

  /** The write is over server-side, one way or another. Keep the key, stop
   *  submitting — resending under a fresh one could repeat the money movement. */
  const spendKey = useCallback(() => {
    setSpent(true);
  }, []);

  return { draftKey, clearKey, spendKey, spent };
}

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
