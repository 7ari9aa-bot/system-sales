import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

/**
 * The live WhatsApp Business app link: is the number connected, and how far did the contacts /
 * history sync get.
 *
 * The status endpoint answers from FIHRIST's own rows, so it is cheap enough to poll — and it has
 * to be polled: history arrives in chunks over minutes, and a screen that asks once shows
 * "importing" forever. The poll stops the moment the state is settled (READY, a refusal, a
 * disconnect), so an idle inbox makes no requests.
 */
export const STATUS_PATH = "/integrations/whatsapp/coexistence-status";

/** A settled state means there is nothing left to wait for. */
export function isSettled(status) {
  if (!status) return false;
  if (status.ready) return true;
  if (status.offboarded) return true;
  const state = String(status.sync_state || "");
  return state === "SYNC_FAILED" || state === "HISTORY_NOT_SHARED" || state === "OFFBOARDED";
}

export function useCoexistenceStatus({ enabled = true, pollMs = 15000 } = {}) {
  const [status, setStatus] = useState(null);
  const [failed, setFailed] = useState(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    if (!enabled) return () => { alive.current = false; };

    let timer = null;
    const load = async () => {
      try {
        const payload = await api(STATUS_PATH);
        if (!alive.current) return;
        setStatus(payload || null);
        setFailed(false);
        if (!isSettled(payload)) timer = setTimeout(load, pollMs);
      } catch {
        // A status banner is a convenience, never a reason to break the thread: one failed read
        // hides the strip and stops asking.
        if (!alive.current) return;
        setFailed(true);
      }
    };
    void load();

    return () => {
      alive.current = false;
      if (timer) clearTimeout(timer);
    };
  }, [enabled, pollMs]);

  return { status, failed };
}
