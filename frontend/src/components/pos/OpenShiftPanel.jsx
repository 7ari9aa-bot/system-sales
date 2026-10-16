import { useEffect, useState } from "react";
import { PlayCircle, Loader2 } from "lucide-react";
import { useT } from "@/lib/i18n";

/** فتح الوردية — الكاشير + البروفايل + الرصيد الافتتاحي لكل وسيلة دفع.
 *
 * الرصيد بيتبني من وسايل البروفايل (زي ERPNext: صف لكل وسيلة برصيد 0)،
 * والكاش بيتكتب في floats_by_method والخادم بيعمل mirror لعمود opening_float. */
export default function OpenShiftPanel({ registers, profiles, busy, onOpen }) {
  const t = useT();

  const [registerId, setRegisterId] = useState("");
  const [profileId, setProfileId] = useState("");
  const [floats, setFloats] = useState({});

  const register = registers.find((r) => r.id === registerId);
  const effectiveProfileId = profileId || register?.profile_id || "";
  const profile = profiles.find((p) => p.id === effectiveProfileId);
  const methods = profile?.allowed_payment_methods?.length
    ? profile.allowed_payment_methods
    : ["cash"];

  // وسايل البروفايل بتزرع صفوف رصيد أول ما البروفايل يتحدد.
  useEffect(() => {
    setFloats((prev) => {
      const next = {};
      for (const m of methods) next[m] = prev[m] ?? "0.00";
      return next;
    });
    // methods بتتغير بس لما البروفايل يتغير.
     
  }, [effectiveProfileId]);

  const setFloat = (method, value) =>
    setFloats((prev) => ({ ...prev, [method]: value }));

  function submit() {
    if (!registerId) return;
    const floatsByMethod = {};
    for (const [method, value] of Object.entries(floats)) {
      const cleaned = String(value || "0.00").trim() || "0.00";
      if (Number(cleaned) !== 0 || method === "cash") {
        floatsByMethod[method] = cleaned;
      }
    }
    onOpen({
      registerId,
      profileId: effectiveProfileId || null,
      floatsByMethod: Object.keys(floatsByMethod).length ? floatsByMethod : null,
      openingFloat: String(floats.cash ?? "0.00").trim() || "0.00",
    });
  }

  return (
    <div className="rounded-2xl bg-card border border-border p-6 max-w-xl">
      <h2 className="font-display text-[16px] font-semibold mb-1">
        {t("pos.openDrawer", "Open the drawer")}
      </h2>
      <p className="text-[13px] text-muted-foreground mb-4">
        {t("pos.openDrawerHint", "Pick a register to start a shift.")}
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-4">
        <label className="block">
          <span className="block text-[12px] text-muted-foreground mb-1">
            {t("pos.pickRegister", "Choose a register…")}
          </span>
          <select
            value={registerId}
            onChange={(e) => setRegisterId(e.target.value)}
            className="h-10 w-full rounded-xl border border-border bg-surface px-3 text-[13px]"
          >
            <option value="">{t("pos.pickRegister", "Choose a register…")}</option>
            {registers.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name} ({r.code})
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="block text-[12px] text-muted-foreground mb-1">
            {t("pos.profile", "Profile")}
          </span>
          <select
            value={effectiveProfileId}
            onChange={(e) => setProfileId(e.target.value)}
            className="h-10 w-full rounded-xl border border-border bg-surface px-3 text-[13px]"
          >
            <option value="">{t("pos.pickProfile", "No profile")}</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.code})
              </option>
            ))}
          </select>
        </label>
      </div>

      {registerId && (
        <div className="mb-4">
          <div className="text-[12.5px] font-medium mb-1.5">
            {t("pos.float", "Opening float")}
          </div>
          <p className="text-[11.5px] text-muted-foreground mb-2">
            {t("pos.floatHint", "Set each payment method's starting float.")}
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2" dir="ltr">
            {methods.map((m) => (
              <label key={m} className="block">
                <span className="block text-[11.5px] text-muted-foreground mb-1">
                  {t(`pos.method.${m}`)}
                </span>
                <input
                  value={floats[m] ?? "0.00"}
                  onChange={(e) => setFloat(m, e.target.value)}
                  inputMode="decimal"
                  dir="ltr"
                  className="h-10 w-full rounded-xl border border-border bg-surface px-3 text-[13px] tabular-nums"
                />
              </label>
            ))}
          </div>
        </div>
      )}

      <button
        type="button"
        onClick={submit}
        disabled={!registerId || busy}
        className="h-11 px-5 rounded-xl bg-primary text-primary-foreground text-[13px] font-medium disabled:opacity-50 inline-flex items-center gap-2"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
        {t("pos.open", "Open")}
      </button>
      {registers.length === 0 && (
        <p className="mt-3 text-[12.5px] text-muted-foreground">
          {t("pos.noRegisters", "No registers yet — create one from Settings.")}
        </p>
      )}
    </div>
  );
}
