"use client";

/** One Idempotency-Key per opened dialog (§91), in one dependency-free home.
 *
 *  This lived inside `../components/orders/order-write-ui.tsx`, but that file
 *  imports order-domain copy at module scope, so reusing the discipline from the
 *  approvals screen would have dragged the money vocabulary along with it. It is
 *  the one genuinely shared piece of the write dialog, so it now lives here: the
 *  rule is identical for any guarded write — one key per OPEN, not per click.
 *  `order-write-ui.tsx` re-exports it so the order dialogs are untouched. */

import { useCallback, useEffect, useRef, useState } from "react";
import { newIdempotencyKey } from "@/lib/api";

/** One Idempotency-Key per opened dialog.
 *
 *  `spent` is set by a terminal refusal (409/412, and for an approval a
 *  "decision already recorded" 400) and is what freezes the submit: the server
 *  said this attempt is over, and the only honest way to get a new key is to open
 *  the dialog again — a new intent. It resets on open, so a close-and-reopen is
 *  the one path to a fresh key, exactly as the guard expects. */
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
   *  submitting — resending under a fresh one could repeat the movement. */
  const spendKey = useCallback(() => {
    setSpent(true);
  }, []);

  return { draftKey, clearKey, spendKey, spent };
}
