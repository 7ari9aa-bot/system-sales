import { Link } from "react-router-dom";
import React, { useState } from "react";
import { TriangleAlert } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { useStartDay, useWorkingSession } from "@/cashier/api/useShifts";
import { parseOpeningBalance } from "@/cashier/api/shiftState";

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
      return "لم يتم تجهيز الكاشير بعد. جهّزه وابدأ اليوم من صفحة الورديات.";
    case "forbidden":
      return "ليست لديك صلاحية استخدام الكاشير.";
    case "unauthorized":
      return "انتهت الجلسة. سجّل الدخول من جديد.";
    default:
      return state?.message || "تعذّر تحميل الكاشير.";
  }
}

/** The step that fixes a blocked till, or null when nothing the user can do here will. */
export function setupAction(state) {
  return state?.status === "needs_setup" ? { label: "تجهيز الكاشير وبدء اليوم", to: "/cashier/shifts" } : null;
}

const CARD = "animate-fade-up mx-auto mt-16 flex max-w-md flex-col items-center gap-3 rounded-2xl border border-border bg-card p-8 text-center";

export function GateMessage({ state }) {
  return (
    <div className={CARD}>
      <TriangleAlert className="h-7 w-7 text-amber-600" aria-hidden="true" />
      <p className="text-sm font-semibold" role="status">{gateMessage(state)}</p>
      {setupAction(state) ? (
        <Button asChild>
          <Link to={setupAction(state).to}>{setupAction(state).label}</Link>
        </Button>
      ) : null}
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
 * The day has not been started: the employee enters the drawer's real balance. Nothing can be
 * sold, returned or exchanged before this, and the figure cannot be skipped or left blank.
 */
export function StartDay({ register, onStart, pending, error }) {
  const [value, setValue] = useState("");
  const parsed = parseOpeningBalance(value);
  const showInvalid = value.trim() !== "" && parsed === null;
  return (
    <form
      className={CARD}
      onSubmit={(e) => {
        e.preventDefault();
        if (parsed !== null && !pending) onStart(parsed);
      }}
    >
      <p className="text-base font-bold">بداية اليوم</p>
      <p className="text-sm text-muted-foreground">
        عُدّ النقدية الموجودة في الدرج الآن وسجّل المبلغ الفعلي{register?.name ? ` (${register.name})` : ""}.
      </p>
      <label className="w-full text-start text-sm font-semibold" htmlFor="opening-balance">رصيد الدرج في بداية اليوم</label>
      <input
        id="opening-balance"
        className="h-11 w-full rounded-lg border border-border bg-background px-3 text-center text-lg tabular-nums"
        inputMode="decimal"
        autoFocus
        autoComplete="off"
        placeholder="0.00"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        aria-invalid={showInvalid}
      />
      {showInvalid && <p className="text-xs text-destructive" role="alert">أدخل رقماً صحيحاً (مثال: 250 أو 250.50).</p>}
      {error && <p className="text-xs text-destructive" role="alert">{error}</p>}
      <Button type="submit" className="w-full" disabled={parsed === null || pending}>
        {pending ? "جارٍ البدء…" : "ابدأ اليوم"}
      </Button>
    </form>
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
  if (state.status === "needs_opening") {
    return <StartDayGate register={state.register} />;
  }
  if (state.status !== "open") return <GateMessage state={state} />;
  return children({ session: state.session, register: state.register });
}

function StartDayGate({ register }) {
  const start = useStartDay();
  return (
    <StartDay
      register={register}
      pending={start.isPending}
      error={start.error?.message}
      onStart={(balance) => start.mutate({ registerId: register.id, balance })}
    />
  );
}
