import React from "react";
import { Save } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { api } from "@/lib/api";
import { SettingCard } from "@/components/settings/SettingsShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** Team policies card — the four `team.*` settings the backend already enforces.
 *
 * Before this card existed the registry carried `team.default_role`,
 * `team.require_2fa`, `team.session_timeout_minutes` and
 * `team.allow_member_invites`, and the server honoured all four
 * (identity/services/tenant.py assigns the default role on invite and refuses
 * invites when disabled, identity/services/auth.py::_resolve_access_ttl reads the
 * timeout, login enforces 2FA) — but no screen could change them, so every owner
 * was stuck on the defaults. They are written through the same `/settings/bulk`
 * path as every other key, which means validation, revision, audit and the
 * approval path all apply; this card does not write a separate API.
 */

export const ROLE_LABELS = {
  cashier: { ar: "كاشير", en: "Cashier" },
  manager: { ar: "مدير", en: "Manager" },
  admin: { ar: "مسؤول", en: "Admin" },
};

export const TEAM_KEYS = [
  "team.default_role",
  "team.require_2fa",
  "team.session_timeout_minutes",
  "team.allow_member_invites",
];

export function roleLabel(role, isAr) {
  const entry = ROLE_LABELS[role];
  if (!entry) return String(role ?? "");
  return isAr ? entry.ar : entry.en;
}

/** Only the keys the user actually changed — an untouched key must not be written,
 * because writing it would bump its revision and fire a settings.changed event. */
export function buildChanges(values, original) {
  const changes = {};
  for (const key of TEAM_KEYS) {
    if (values[key] !== undefined && values[key] !== original[key]) changes[key] = values[key];
  }
  return changes;
}

/** What the server's answer means for the person looking at the screen.
 *
 * `/settings/bulk` has three honest outcomes and the card must not blur them:
 * applied, held for approval (`team.require_2fa` is SENSITIVE, so a second
 * person may have to approve it), or refused by validation.
 */
export function describeResult(res, isAr) {
  const pending = res?.pending_approval || [];
  if (pending.length > 0) {
    return {
      notice: "",
      error: isAr
        ? `تم إرسال ${pending.length} إعداد للموافقة قبل التطبيق: ${pending.join("، ")}`
        : `${pending.length} setting(s) need approval before they apply: ${pending.join(", ")}`,
      pending,
    };
  }
  return { notice: isAr ? "تم الحفظ" : "Saved", error: "", pending: [] };
}

/** A single control, drawn from the registry definition (never hard-coded per key). */
export function TeamField({ def, value, onChange, isAr }) {
  const label = isAr ? def.label_ar : def.label_en || def.key;
  const help = isAr ? def.description_ar : def.description_en;
  const id = `team-${def.key}`;

  let control = null;
  if (def.type === "bool") {
    control = (
      <button
        type="button"
        role="switch"
        aria-checked={value === true}
        aria-label={label}
        onClick={() => onChange(!value)}
        className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
          value === true ? "bg-indigo-600" : "bg-slate-300"
        }`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${
            value === true ? "left-[22px]" : "left-0.5"
          }`}
        />
      </button>
    );
  } else if (def.type === "enum") {
    control = (
      <select
        id={id}
        value={value ?? def.default ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 rounded-md border border-slate-300 bg-white px-3 text-sm"
      >
        {(def.allowed_values || []).map((option) => (
          <option key={option} value={option}>
            {roleLabel(option, isAr)}
          </option>
        ))}
      </select>
    );
  } else if (def.type === "number") {
    control = (
      <Input
        id={id}
        inputMode="decimal"
        type="number"
        min={def.min_value ?? undefined}
        max={def.max_value ?? undefined}
        value={value ?? def.default ?? 0}
        onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
        className="w-32"
      />
    );
  } else {
    control = (
      <p className="text-sm text-slate-500">
        {isAr ? "هذا الإعداد لا يمكن تعديله من هنا" : "This setting cannot be edited here"}
      </p>
    );
  }

  return (
    <div className="flex items-start justify-between gap-4 border-b border-slate-100 py-3 last:border-0">
      <div className="min-w-0">
        <label htmlFor={id} className="text-sm font-medium text-slate-800">
          {label}
        </label>
        {help ? <p className="mt-0.5 text-xs text-slate-500">{help}</p> : null}
      </div>
      <div className="shrink-0">{control}</div>
    </div>
  );
}

export default function TeamPolicyCard() {
  const { lang } = useI18n();
  const isAr = lang === "ar";

  const [defs, setDefs] = React.useState(null);
  const [values, setValues] = React.useState({});
  const [original, setOriginal] = React.useState({});
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    Promise.all([api("/settings/definitions?domain=team"), api("/settings/effective?domain=team")])
      .then(([teamDefs, teamEff]) => {
        if (!alive) return;
        setDefs(teamDefs || []);
        const next = {};
        for (const [key, resolved] of Object.entries(teamEff || {})) next[key] = resolved.value;
        setValues(next);
        setOriginal(next);
      })
      .catch((err) => {
        if (alive) setError(err?.message || (isAr ? "تعذر تحميل الإعدادات" : "Could not load settings"));
      });
    return () => {
      alive = false;
    };
  }, [isAr]);

  const changes = buildChanges(values, original);
  const dirty = Object.keys(changes).length > 0;

  async function save() {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const res = await api("/settings/bulk", {
        method: "POST",
        body: { scope: "tenant", settings: changes },
      });
      const outcome = describeResult(res, isAr);
      setNotice(outcome.notice);
      setError(outcome.error);
      // A key held for approval has NOT changed yet, so it stays dirty.
      const applied = {};
      for (const key of Object.keys(changes)) {
        if (!outcome.pending.includes(key)) applied[key] = changes[key];
      }
      const merged = { ...original, ...applied };
      setOriginal(merged);
      setValues((current) => ({ ...current, ...merged }));
    } catch (err) {
      const conflicts = err?.details?.conflicting_keys || err?.body?.details?.conflicting_keys;
      if (conflicts?.length) {
        setError(
          isAr
            ? `حدّث الصفحة: ${conflicts.length} إعداد اتغيّر من مكان تاني (${conflicts.join("، ")})`
            : `Reload the page: ${conflicts.length} setting(s) changed elsewhere (${conflicts.join(", ")})`,
        );
      } else {
        setError(err?.message || (isAr ? "تعذر الحفظ" : "Could not save"));
      }
    } finally {
      setSaving(false);
    }
  }

  const ordered = defs
    ? TEAM_KEYS.map((key) => defs.find((d) => d.key === key)).filter(Boolean)
    : [];

  return (
    <SettingCard
      title={isAr ? "سياسات الفريق" : "Team policies"}
      desc={
        isAr
          ? "الدور الافتراضي للعضو الجديد، وإلزام المصادقة الثنائية، ومدة الجلسة، والسماح بالدعوات."
          : "Default role for a new member, required 2FA, session length, and whether invites are allowed."
      }
    >
      {error ? <p className="mb-3 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p> : null}
      {notice ? (
        <p className="mb-3 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</p>
      ) : null}

      {defs === null && !error ? (
        <p className="py-4 text-sm text-slate-500">{isAr ? "جارٍ التحميل…" : "Loading…"}</p>
      ) : null}

      {ordered.map((def) => (
        <TeamField
          key={def.key}
          def={def}
          isAr={isAr}
          value={values[def.key]}
          onChange={(next) => setValues((current) => ({ ...current, [def.key]: next }))}
        />
      ))}

      <div className="mt-4 flex justify-end">
        <Button onClick={save} disabled={!dirty || saving}>
          <Save className="mr-2 h-4 w-4" />
          {saving ? (isAr ? "جارٍ الحفظ…" : "Saving…") : isAr ? "حفظ" : "Save"}
        </Button>
      </div>
    </SettingCard>
  );
}
