import React from "react";
import { Loader2, Plus, ScanLine, Trash2 } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import SettingsShell, { SettingCard } from "@/components/settings/SettingsShell";

/** إعدادات الكاشير — البروفايلات والكاشيرات وسماحيات الموظفين.
 *
 * كل شيء هنا بيمر على /api/v1/pos — نفس العقود اللي شاشة الكاشير بتقراها.
 * البروفايل بيسمع: مخزن، عميل walk-in، وسايل دفع مسموحة، سقف خصم (اختياري
 * للمالك — الباب مقفول عنده افتراضياً بـ 100 يعني حرية كاملة للكاشير). */

const METHODS = ["cash", "card", "wallet", "bank_transfer"];

function Toggle({ checked, onChange, label }) {
  return (
    <label className="inline-flex items-center gap-2 text-[13px] text-foreground">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function CeilingFields({ value, onChange, t }) {
  const field = (key, labelKey, fallback) => (
    <label className="flex flex-col gap-1 text-[12px] text-muted-foreground">
      {t(labelKey, fallback)}
      <input
        value={value[key] ?? ""}
        onChange={(e) => onChange({ ...value, [key]: e.target.value })}
        dir="ltr"
        inputMode="decimal"
        placeholder={key === "discount_ceiling_pct" ? "0" : "∞"}
        className="h-9 rounded-xl border border-border bg-surface px-3 text-[13px] tabular-nums text-foreground"
      />
    </label>
  );
  return (
    <div className="flex flex-col gap-1">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {field("discount_ceiling_pct", "posSettings.discountCeiling", "Max discount without a manager (%)")}
        {field("refund_ceiling", "posSettings.refundCeiling", "Max return without a manager (EGP)")}
        {field("cash_out_ceiling", "posSettings.cashOutCeiling", "Max cash out without a manager (EGP)")}
      </div>
      <span className="text-[11px] text-muted-foreground">
        {t(
          "posSettings.ceilingHint",
          "Leave empty for no limit: the cashier can do any amount. Above the limit a manager PIN is needed."
        )}
      </span>
    </div>
  );
}

export default function PosSettings() {
  const t = useT();

  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");

  const [profiles, setProfiles] = React.useState([]);
  const [registers, setRegisters] = React.useState([]);
  const [warehouses, setWarehouses] = React.useState([]);
  const [customers, setCustomers] = React.useState([]);
  const [members, setMembers] = React.useState([]);

  const [showProfileForm, setShowProfileForm] = React.useState(false);
  const [editing, setEditing] = React.useState(null); // profile id under edit

  const [profileForm, setProfileForm] = React.useState({
    name: "",
    code: "",
    warehouse_id: "",
    default_customer_id: "",
    default_payment_method: "cash",
    allowed_payment_methods: ["cash", "card", "wallet", "bank_transfer"],
    discount_ceiling_pct: "100.00",
    refund_ceiling: "",
    cash_out_ceiling: "",
    require_customer: false,
  });
  const [registerForm, setRegisterForm] = React.useState({
    name: "",
    code: "",
    warehouse_id: "",
    profile_id: "",
  });
  const [grantByProfile, setGrantByProfile] = React.useState({});
  const [grantUser, setGrantUser] = React.useState({});

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const [profiles, registers, warehouses, customers, members] = await Promise.all([
        api("/pos/profiles"),
        api("/pos/registers"),
        api("/warehouses?limit=200"),
        api("/customers?limit=100"),
        api("/users"),
      ]);
      const profileRows = Array.isArray(profiles) ? profiles : [];
      // المسموحين لكل بروفايل — بأسمائهم الحقيقية من نفس الـ endpoint.
      const withGrantees = await Promise.all(
        profileRows.map(async (row) => {
          try {
            const grantees = await api(`/pos/profiles/${row.id}/users`);
            return { ...row, _grantees: Array.isArray(grantees) ? grantees : [] };
          } catch {
            return { ...row, _grantees: [] };
          }
        })
      );
      setProfiles(withGrantees);
      setRegisters(Array.isArray(registers) ? registers : []);
      setWarehouses(Array.isArray(warehouses) ? warehouses : []);
      setCustomers(
        Array.isArray(customers)
          ? customers
          : Array.isArray(customers?.items)
            ? customers.items
            : []
      );
      setMembers(Array.isArray(members) ? members : []);
      setError("");
    } catch (e) {
      setError(e?.message || t("posSettings.err.load", "Could not load the cashier settings."));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  function flash(message) {
    setNotice(message);
    setError("");
  }

  // ------------------------------------------------------------- profiles --

  async function createProfile() {
    try {
      await api("/pos/profiles", {
        method: "POST",
        body: {
          name: profileForm.name,
          code: profileForm.code,
          warehouse_id: profileForm.warehouse_id,
          default_customer_id: profileForm.default_customer_id || undefined,
          default_payment_method: profileForm.default_payment_method,
          allowed_payment_methods: profileForm.allowed_payment_methods,
          discount_ceiling_pct: profileForm.discount_ceiling_pct,
          refund_ceiling: profileForm.refund_ceiling || null,
          cash_out_ceiling: profileForm.cash_out_ceiling || null,
          require_customer: profileForm.require_customer,
        },
      });
      setShowProfileForm(false);
      setProfileForm({
        name: "",
        code: "",
        warehouse_id: profileForm.warehouse_id,
        default_customer_id: "",
        default_payment_method: "cash",
        allowed_payment_methods: ["cash", "card", "wallet", "bank_transfer"],
        discount_ceiling_pct: "100.00",
        refund_ceiling: "",
        cash_out_ceiling: "",
        require_customer: false,
      });
      await load();
      flash(t("posSettings.created", "Profile created."));
    } catch (e) {
      setError(e?.message || t("posSettings.err.save", "Could not save the profile."));
    }
  }

  async function saveProfile(p) {
    try {
      await api(`/pos/profiles/${p.id}`, {
        method: "PATCH",
        body: {
          name: p.name,
          warehouse_id: p.warehouse_id,
          default_customer_id: p.default_customer_id || undefined,
          default_payment_method: p.default_payment_method || undefined,
          allowed_payment_methods: p.allowed_payment_methods,
          discount_ceiling_pct: p.discount_ceiling_pct,
          refund_ceiling: p.refund_ceiling || null,
          cash_out_ceiling: p.cash_out_ceiling || null,
          require_customer: p.require_customer,
        },
      });
      setEditing(null);
      await load();
      flash(t("posSettings.saved", "Profile updated."));
    } catch (e) {
      setError(e?.message || t("posSettings.err.save", "Could not save the profile."));
    }
  }

  function toggleMethod(profile, method) {
    setProfiles((prev) =>
      prev.map((row) =>
        row.id === profile.id
          ? {
              ...row,
              allowed_payment_methods: row.allowed_payment_methods.includes(method)
                ? row.allowed_payment_methods.filter((m) => m !== method)
                : [...row.allowed_payment_methods, method],
            }
          : row
      )
    );
  }

  // ------------------------------------------------------------ registers --

  async function createRegister() {
    try {
      await api("/pos/registers", {
        method: "POST",
        body: {
          name: registerForm.name,
          code: registerForm.code,
          warehouse_id: registerForm.warehouse_id,
          profile_id: registerForm.profile_id || undefined,
        },
      });
      setRegisterForm({ name: "", code: "", warehouse_id: registerForm.warehouse_id, profile_id: "" });
      await load();
      flash(t("posSettings.registerCreated", "Register created."));
    } catch (e) {
      setError(e?.message || t("posSettings.err.register", "Could not create the register."));
    }
  }

  // -------------------------------------------------------------- grantees --

  async function grant(profile) {
    const userId = grantUser[profile.id];
    if (!userId) return;
    try {
      await api(`/pos/profiles/${profile.id}/users`, {
        method: "POST",
        body: { user_id: userId },
      });
      setGrantUser((prev) => ({ ...prev, [profile.id]: "" }));
      await load();
      flash(t("posSettings.granted", "Cashier granted."));
    } catch (e) {
      setError(e?.message || t("posSettings.err.grant", "Could not grant the cashier."));
    }
  }

  async function revoke(profile, userId) {
    try {
      await api(`/pos/profiles/${profile.id}/users/${userId}`, { method: "DELETE" });
      await load();
    } catch (e) {
      setError(e?.message || t("posSettings.err.revoke", "Could not revoke the cashier."));
    }
  }

  const whName = (id) => warehouses.find((w) => w.id === id)?.name || "—";
  const custName = (id) => customers.find((c) => c.id === id)?.name || "—";

  return (
    <SettingsShell>
      {error && (
        <div role="alert" className="mb-4 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-2.5 text-[13px] text-destructive">
          {error}
        </div>
      )}
      {notice && (
        <div role="status" className="mb-4 rounded-xl border border-success/30 bg-success/10 px-4 py-2.5 text-[13px] text-success">
          {notice}
        </div>
      )}

      {/* البروفايلات */}
      <SettingCard
        title={t("posSettings.profiles", "Cashier profiles")}
        desc={t("posSettings.profilesDesc", "One profile preconfigures a till: warehouse, walk-in customer, payment methods.")}
      >
        {loading ? (
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        ) : (
          <>
            <div className="space-y-3">
              {profiles.length === 0 && (
                <p className="text-[13px] text-muted-foreground">
                  {t("posSettings.noProfiles", "No profiles yet — create one below.")}
                </p>
              )}
              {profiles.map((p) => {
                const isEditing = editing === p.id;
                return (
                  <div key={p.id} className="rounded-xl border border-border p-3 space-y-2">
                    {isEditing ? (
                      <div className="space-y-2">
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                          <input
                            value={p.name}
                            onChange={(e) =>
                              setProfiles((prev) => prev.map((row) => (row.id === p.id ? { ...row, name: e.target.value } : row)))
                            }
                            className="h-9 rounded-xl border border-border bg-surface px-3 text-[13px]"
                          />
                          <select
                            value={p.warehouse_id}
                            onChange={(e) =>
                              setProfiles((prev) => prev.map((row) => (row.id === p.id ? { ...row, warehouse_id: e.target.value } : row)))
                            }
                            className="h-9 rounded-xl border border-border bg-surface px-3 text-[13px]"
                          >
                            {warehouses.map((w) => (
                              <option key={w.id} value={w.id}>
                                {w.name}
                              </option>
                            ))}
                          </select>
                          <select
                            value={p.default_customer_id || ""}
                            onChange={(e) =>
                              setProfiles((prev) => prev.map((row) => (row.id === p.id ? { ...row, default_customer_id: e.target.value } : row)))
                            }
                            className="h-9 rounded-xl border border-border bg-surface px-3 text-[13px]"
                          >
                            <option value="">{t("posSettings.noWalkIn", "No walk-in customer")}</option>
                            {customers.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.name}
                              </option>
                            ))}
                          </select>
                          <CeilingFields
                            t={t}
                            value={p}
                            onChange={(next) =>
                              setProfiles((prev) => prev.map((row) => (row.id === p.id ? { ...row, ...next } : row)))
                            }
                          />
                        </div>
                        <div className="flex flex-wrap gap-3">
                          {METHODS.map((m) => (
                            <Toggle
                              key={m}
                              checked={p.allowed_payment_methods.includes(m)}
                              onChange={() => toggleMethod(p, m)}
                              label={t(`pos.method.${m}`)}
                            />
                          ))}
                        </div>
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={() => void saveProfile(p)}
                            className="h-9 px-4 rounded-xl bg-primary text-primary-foreground text-[13px] font-medium"
                          >
                            {t("posSettings.save", "Save")}
                          </button>
                          <button
                            type="button"
                            onClick={() => setEditing(null)}
                            className="h-9 px-4 rounded-xl border border-border text-[13px]"
                          >
                            {t("posSettings.cancel", "Cancel")}
                          </button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="flex items-center justify-between">
                          <div>
                            <div className="text-[13.5px] font-medium">
                              {p.name} <span className="text-muted-foreground" dir="ltr">({p.code})</span>
                            </div>
                            <div className="text-[12px] text-muted-foreground">
                              {t("posSettings.warehouse", "Warehouse")}: {whName(p.warehouse_id)} ·{" "}
                              {t("posSettings.walkIn", "Walk-in")}: {p.default_customer_id ? custName(p.default_customer_id) : t("posSettings.none", "none")}
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            {!p.is_active && (
                              <span className="text-[11.5px] text-muted-foreground">{t("posSettings.inactive", "inactive")}</span>
                            )}
                            <button
                              type="button"
                              onClick={() => setEditing(isEditing ? null : p.id)}
                              className="h-8 px-3 rounded-lg border border-border text-[12.5px]"
                            >
                              {isEditing ? t("posSettings.cancel", "Cancel") : t("posSettings.edit", "Edit")}
                            </button>
                          </div>
                        </div>
                        {/* الكاشيرين المسموحين */}
                        <div className="text-[12px] text-muted-foreground">
                          {t("posSettings.grantees", "Granted cashiers")}:
                        </div>
                        <ul className="flex flex-wrap gap-1.5">
                          {(p._grantees || []).length === 0 && (
                            <li className="text-[12px] text-muted-foreground">
                              {t("posSettings.noGrantees", "Everyone with orders:write (no restriction)")}
                            </li>
                          )}
                          {(p._grantees || []).map((g) => (
                            <li key={g.user_id} className="inline-flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-[11.5px]">
                              {g.full_name || g.user_id.slice(0, 8)}
                              <button
                                type="button"
                                aria-label={t("posSettings.revoke", "Revoke")}
                                onClick={() => void revoke(p, g.user_id)}
                                className="text-destructive"
                              >
                                <Trash2 className="h-3 w-3" />
                              </button>
                            </li>
                          ))}
                        </ul>
                        <div className="flex gap-2">
                          <select
                            value={grantUser[p.id] || ""}
                            onChange={(e) => setGrantUser((prev) => ({ ...prev, [p.id]: e.target.value }))}
                            className="h-9 flex-1 rounded-xl border border-border bg-surface px-3 text-[13px]"
                          >
                            <option value="">{t("posSettings.pickMember", "Pick a team member…")}</option>
                            {members
                              .filter((m) => !(p._grantees || []).some((g) => g.user_id === m.id))
                              .map((m) => (
                                <option key={m.id} value={m.id}>
                                  {m.full_name || m.email} — {t(`posSettings.role.${m.role_code}`, m.role_code)}
                                </option>
                              ))}
                          </select>
                          <button
                            type="button"
                            onClick={() => void grant(p)}
                            disabled={!grantUser[p.id]}
                            className="h-9 px-3 rounded-xl border border-border text-[12.5px] font-medium disabled:opacity-50 inline-flex items-center gap-1.5"
                          >
                            <Plus className="h-3.5 w-3.5" />
                            {t("posSettings.grant", "Grant")}
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                );
              })}
            </div>

            {!showProfileForm ? (
              <button
                type="button"
                onClick={() => setShowProfileForm(true)}
                className="mt-3 h-9 px-4 rounded-xl border border-border text-[13px] font-medium inline-flex items-center gap-1.5"
              >
                <Plus className="h-4 w-4" />
                {t("posSettings.newProfile", "New profile")}
              </button>
            ) : (
              <div className="mt-3 rounded-xl border border-primary/40 p-3 space-y-2">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  <input
                    value={profileForm.name}
                    onChange={(e) => setProfileForm((prev) => ({ ...prev, name: e.target.value }))}
                    placeholder={t("posSettings.name", "Name")}
                    className="h-9 rounded-xl border border-border bg-surface px-3 text-[13px]"
                  />
                  <input
                    value={profileForm.code}
                    onChange={(e) => setProfileForm((prev) => ({ ...prev, code: e.target.value }))}
                    placeholder={t("posSettings.code", "Code (e.g. MAIN)")}
                    dir="ltr"
                    className="h-9 rounded-xl border border-border bg-surface px-3 text-[13px]"
                  />
                  <select
                    value={profileForm.warehouse_id}
                    onChange={(e) => setProfileForm((prev) => ({ ...prev, warehouse_id: e.target.value }))}
                    className="h-9 rounded-xl border border-border bg-surface px-3 text-[13px]"
                  >
                    <option value="">{t("posSettings.pickWarehouse", "Pick a warehouse…")}</option>
                    {warehouses.map((w) => (
                      <option key={w.id} value={w.id}>
                        {w.name}
                      </option>
                    ))}
                  </select>
                  <select
                    value={profileForm.default_customer_id}
                    onChange={(e) => setProfileForm((prev) => ({ ...prev, default_customer_id: e.target.value }))}
                    className="h-9 rounded-xl border border-border bg-surface px-3 text-[13px]"
                  >
                    <option value="">{t("posSettings.noWalkIn", "No walk-in customer")}</option>
                    {customers.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </div>
                <CeilingFields t={t} value={profileForm} onChange={setProfileForm} />
                <div className="flex flex-wrap gap-3">
                  {METHODS.map((m) => (
                    <Toggle
                      key={m}
                      checked={profileForm.allowed_payment_methods.includes(m)}
                      onChange={() =>
                        setProfileForm((prev) => ({
                          ...prev,
                          allowed_payment_methods: prev.allowed_payment_methods.includes(m)
                            ? prev.allowed_payment_methods.filter((x) => x !== m)
                            : [...prev.allowed_payment_methods, m],
                        }))
                      }
                      label={t(`pos.method.${m}`)}
                    />
                  ))}
                </div>
                <button
                  type="button"
                  onClick={() => void createProfile()}
                  disabled={!profileForm.name || !profileForm.code || !profileForm.warehouse_id}
                  className="h-9 px-4 rounded-xl bg-primary text-primary-foreground text-[13px] font-medium disabled:opacity-50"
                >
                  {t("posSettings.create", "Create profile")}
                </button>
              </div>
            )}
          </>
        )}
      </SettingCard>

      {/* الكاشيرات */}
      <SettingCard
        title={t("posSettings.registers", "Registers")}
        desc={t("posSettings.registersDesc", "The physical tills. Each sells from one warehouse, optionally under a profile.")}
      >
        <ul className="space-y-1.5 mb-3">
          {registers.length === 0 && (
            <li className="text-[13px] text-muted-foreground">
              {t("posSettings.noRegisters", "No registers yet — create one below.")}
            </li>
          )}
          {registers.map((r) => (
            <li key={r.id} className="flex items-center justify-between rounded-xl border border-border px-3 py-2 text-[13px]">
              <span>
                {r.name} <span className="text-muted-foreground" dir="ltr">({r.code})</span>
              </span>
              <span className="text-[12px] text-muted-foreground">
                {whName(r.warehouse_id)}
                {r.profile_id ? ` · ${profiles.find((x) => x.id === r.profile_id)?.name || ""}` : ""}
              </span>
            </li>
          ))}
        </ul>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-2">
          <input
            value={registerForm.name}
            onChange={(e) => setRegisterForm((prev) => ({ ...prev, name: e.target.value }))}
            placeholder={t("posSettings.name", "Name")}
            className="h-9 rounded-xl border border-border bg-surface px-3 text-[13px]"
          />
          <input
            value={registerForm.code}
            onChange={(e) => setRegisterForm((prev) => ({ ...prev, code: e.target.value }))}
            placeholder={t("posSettings.code", "Code (e.g. T1)")}
            dir="ltr"
            className="h-9 rounded-xl border border-border bg-surface px-3 text-[13px]"
          />
          <select
            value={registerForm.warehouse_id}
            onChange={(e) => setRegisterForm((prev) => ({ ...prev, warehouse_id: e.target.value }))}
            className="h-9 rounded-xl border border-border bg-surface px-3 text-[13px]"
          >
            <option value="">{t("posSettings.pickWarehouse", "Pick a warehouse…")}</option>
            {warehouses.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
          <select
            value={registerForm.profile_id}
            onChange={(e) => setRegisterForm((prev) => ({ ...prev, profile_id: e.target.value }))}
            className="h-9 rounded-xl border border-border bg-surface px-3 text-[13px]"
          >
            <option value="">{t("posSettings.pickProfile", "No profile")}</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <button
          type="button"
          onClick={() => void createRegister()}
          disabled={!registerForm.name || !registerForm.code || !registerForm.warehouse_id}
          className="mt-2 h-9 px-4 rounded-xl bg-primary text-primary-foreground text-[13px] font-medium disabled:opacity-50 inline-flex items-center gap-1.5"
        >
          <ScanLine className="h-4 w-4" />
          {t("posSettings.createRegister", "Create register")}
        </button>
      </SettingCard>
    </SettingsShell>
  );
}
