import { Link } from "react-router-dom";
import React, { useState } from "react";
import { TriangleAlert } from "lucide-react";
import { Button } from "@/applications/apparel/components/ui/button";
import { useStartDay, useWorkingSession } from "@/applications/apparel/api/useShifts";
import { parseOpeningBalance } from "@/applications/apparel/api/shiftState";
import PageSkeleton from "@/applications/apparel/components/ui-kit/PageSkeleton";

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

// The two names the shop's first till is created with. They are shown as plain Arabic; any name a
// person typed themselves is shown exactly as typed.
const FACTORY_TILL_NAMES = new Set(["main till", "main"]);

/** The till's name as the screen shows it. Pure, so it can be tested without a screen. */
export function tillLabel(register) {
  const name = String(register?.name ?? "").trim();
  if (!name) return "";
  return FACTORY_TILL_NAMES.has(name.toLowerCase()) ? "الدرج الرئيسي" : name;
}

/** The opening-cash instruction. The till name and the closing dot are one unbreakable piece. */
export function startDayParts(register) {
  const label = tillLabel(register);
  return {
    lead: "عُدّ النقدية الموجودة في الدرج الآن وسجّل المبلغ الفعلي",
    tail: label ? ` (${label}).` : ".",
  };
}

/** How the start button looks. While it waits for the number it must still read as a button. */
export function startButtonLook(waiting) {
  return waiting
    ? { className: "pos-start-day pos-start-day--waiting h-11 w-full border-2 border-orange-500 bg-orange-200 text-base font-bold text-orange-950 disabled:opacity-100", waiting: true }
    : { className: "pos-start-day w-full", waiting: false };
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
        {startDayParts(register).lead}
        <span className="whitespace-nowrap">{startDayParts(register).tail}</span>
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
      {value.trim() === "" && (
        <p className="text-xs text-muted-foreground">اكتب رصيد الدرج لتفعيل زر البدء (اكتب 0 لو الدرج فاضي).</p>
      )}
      <Button
        type="submit"
        className={startButtonLook(parsed === null || pending).className}
        disabled={parsed === null || pending}
      >
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
    return <PageSkeleton label="جارٍ قراءة حالة الوردية…" rows={3} testId="working-session-gate-loading" />;
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
