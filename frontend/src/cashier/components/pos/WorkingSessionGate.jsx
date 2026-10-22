import React, { useState } from "react";
import { TriangleAlert } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { useWorkingSession } from "@/cashier/api/useShifts";

const PICK_KEY = "cashier:register";

// The till a person chose stays chosen across the sales, returns and exchange screens for this
// browser tab, so they are asked once, not on every screen.
export function readPickedRegister() {
  try {
    return globalThis.sessionStorage?.getItem(PICK_KEY) || null;
  } catch {
    return null;
  }
}
function rememberRegister(id) {
  try {
    globalThis.sessionStorage?.setItem(PICK_KEY, id);
  } catch {
    /* private mode: the pick just lasts for this screen */
  }
}

/** The message for a till that cannot be used. Pure, so it can be tested without a screen. */
export function gateMessage(state) {
  switch (state?.status) {
    case "needs_setup":
      return "لم يتم تجهيز الكاشير بعد. اطلب من المدير تجهيزه من الإعدادات.";
    case "forbidden":
      return "ليست لديك صلاحية استخدام الكاشير.";
    case "unauthorized":
      return "انتهت الجلسة. سجّل الدخول من جديد.";
    default:
      return state?.message || "تعذّر تحميل الكاشير.";
  }
}

const CARD = "animate-fade-up mx-auto mt-16 flex max-w-md flex-col items-center gap-3 rounded-2xl border border-border bg-card p-8 text-center";

export function GateMessage({ state }) {
  return (
    <div className={CARD}>
      <TriangleAlert className="h-7 w-7 text-amber-600" aria-hidden="true" />
      <p className="text-sm font-semibold" role="status">{gateMessage(state)}</p>
    </div>
  );
}

/** Several active tills and none picked yet: ask once, never guess the first one. */
export function ChooseRegister({ registers, onPick }) {
  return (
    <div className={CARD}>
      <p className="text-sm font-semibold" role="status">اختر جهاز الكاشير الذي ستعمل عليه</p>
      <div className="flex w-full flex-col gap-2">
        {registers.map((r) => (
          <Button key={r.id} variant="outline" onClick={() => onPick(r.id)}>{r.name || r.code}</Button>
        ))}
      </div>
    </div>
  );
}

/**
 * Gives `children` today's working session of the till, so a screen needs no shift to be open.
 * `children` is a function: ({ session, register }) => element.
 */
export default function WorkingSessionGate({ children }) {
  const [registerId, setRegisterId] = useState(readPickedRegister);
  const till = useWorkingSession({ registerId });
  if (till.isLoading) {
    return <p className="p-8 text-center text-sm text-muted-foreground" role="status">جارٍ التحميل…</p>;
  }
  const state = till.data ?? { status: "error", message: till.error?.message };
  if (state.status === "choose") {
    return (
      <ChooseRegister
        registers={state.registers}
        onPick={(id) => {
          rememberRegister(id);
          setRegisterId(id);
        }}
      />
    );
  }
  if (state.status !== "open") return <GateMessage state={state} />;
  return children({ session: state.session, register: state.register });
}
