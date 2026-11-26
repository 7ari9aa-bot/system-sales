/** The four pages that describe one branch: its data, its week, its staff, its scopes.
 *
 * A branch is a `locations` row inside a `workspace` — the same row the POS, the registers and
 * the access grants already point at. So every panel here picks a real branch and writes through
 * the hierarchy endpoints; none of them invents a parallel "branch" object in settings.
 *
 * The scope panel is deliberately read-only: it answers "what does this branch actually use, and
 * what did it inherit from the store" from the settings engine's own resolution, so there is no
 * second place where a branch value could be edited.
 */
import React from "react";
import { Check, Loader2, Plus, Save, Trash2 } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import { SettingCard } from "@/components/settings/SettingsShell";
import { Badge } from "@/components/dashboard/ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

/** The week as the backend expects it.
 *
 * A day is claimed only when the shop actually said something about it: closed, or open with both
 * times. A day left half-filled is dropped rather than guessed at, because "open 09:00 with no
 * closing time" is not a week anyone meant. An empty result is `{}`, which the service reads as
 * "follows the store" — the same statement as clearing the hours.
 */
export function hoursPayload(days) {
  const payload = {};
  for (const day of DAYS) {
    const d = days[day];
    if (!d) continue;
    if (d.closed) payload[day] = { closed: true };
    else if (d.open && d.close) payload[day] = { open: d.open, close: d.close };
  }
  return payload;
}

/** Every branch the tenant has, flattened, with the workspace it sits in. */
function useBranches() {
  const t = useT();
  const [state, setState] = React.useState({ loading: true, error: "", branches: [] });
  const [nonce, setNonce] = React.useState(0);

  React.useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await api("/hierarchy/workspaces");
        const workspaces = Array.isArray(res?.items) ? res.items : [];
        const withLocations = await Promise.all(
          workspaces.map(async (w) => {
            try {
              const locs = await api(`/hierarchy/workspaces/${w.id}/locations`);
              return (Array.isArray(locs?.items) ? locs.items : []).map((l) => ({
                ...l,
                workspaceName: w.name,
              }));
            } catch {
              return [];
            }
          }),
        );
        if (alive) {
          setState({ loading: false, error: "", branches: withLocations.flat() });
        }
      } catch (e) {
        if (alive) {
          setState({ loading: false, error: e?.message || t("settings.locations.loadError"), branches: [] });
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [t, nonce]);

  return { ...state, reload: () => setNonce((n) => n + 1) };
}

function BranchPicker({ branches, value, onChange, label }) {
  if (branches.length === 0) return null;
  return (
    <label className="flex items-center gap-2 py-2 text-[13px]">
      <span className="text-muted-foreground">{label}</span>
      <select
        className="rounded-md border border-border bg-background px-2 py-1 text-[13px]"
        value={value || ""}
        onChange={(e) => onChange(e.target.value)}
      >
        {branches.map((b) => (
          <option key={b.id} value={b.id}>
            {b.workspaceName} · {b.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function Empty({ children }) {
  return <p className="py-3 text-[13px] text-muted-foreground">{children}</p>;
}

function Loading() {
  const t = useT();
  return (
    <div className="flex items-center gap-2 py-6 text-[13px] text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" /> {t("settings.locations.loading")}
    </div>
  );
}

function Failed({ message }) {
  return (
    <div role="alert" className="text-[13px] text-destructive">
      {message}
    </div>
  );
}

function Notice({ children }) {
  if (!children) return null;
  return (
    <span className="flex items-center gap-1 text-[12.5px] text-emerald-600">
      <Check className="h-3.5 w-3.5" /> {children}
    </span>
  );
}

/** Branch data — the three facts the row actually carries. */
export function BranchDataPanel() {
  const t = useT();
  const { loading, error, branches, reload } = useBranches();
  const [branchId, setBranchId] = React.useState("");
  const branch = branches.find((b) => b.id === branchId) || branches[0];
  const [form, setForm] = React.useState(null);
  const [saving, setSaving] = React.useState(false);
  const [notice, setNotice] = React.useState("");
  const [saveError, setSaveError] = React.useState("");

  React.useEffect(() => {
    if (!branch) return;
    setForm({ name: branch.name, code: branch.code || "", is_active: branch.is_active });
    setNotice("");
    setSaveError("");
  }, [branch?.id]);

  if (loading) return <Loading />;
  if (error) return <Failed message={error} />;
  if (branches.length === 0) {
    return (
      <SettingCard title={t("settings.locations.data.title")} desc={t("settings.locations.data.desc")}>
        <Empty>{t("settings.locations.branches.empty")}</Empty>
      </SettingCard>
    );
  }

  const save = async () => {
    setSaving(true);
    setSaveError("");
    setNotice("");
    try {
      await api(`/hierarchy/locations/${branch.id}`, {
        method: "PATCH",
        body: {
          name: form.name,
          code: form.code || null,
          is_active: form.is_active,
        },
      });
      setNotice(t("settings.locations.saved"));
      reload();
    } catch (e) {
      setSaveError(e?.message || t("settings.locations.saveError"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <SettingCard title={t("settings.locations.data.title")} desc={t("settings.locations.data.desc")}>
      <BranchPicker
        branches={branches}
        value={branch.id}
        onChange={setBranchId}
        label={t("settings.locations.pick")}
      />
      {form && (
        <div className="space-y-2.5 border-t border-border pt-2.5">
          <label className="block text-[13px]">
            <span className="text-muted-foreground">{t("settings.locations.data.name")}</span>
            <Input
              className="mt-1"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </label>
          <label className="block text-[13px]">
            <span className="text-muted-foreground">{t("settings.locations.data.code")}</span>
            <Input
              className="mt-1 max-w-[12rem]"
              value={form.code}
              onChange={(e) => setForm({ ...form, code: e.target.value })}
            />
            <span className="mt-1 block text-[12px] text-muted-foreground">
              {t("settings.locations.data.codeHint")}
            </span>
          </label>
          <label className="flex items-center gap-2 text-[13px]">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
            />
            {t("settings.locations.data.active")}
          </label>
          <div className="flex items-center gap-3 pt-1">
            <Button size="sm" onClick={save} disabled={saving}>
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
              {t("settings.locations.save")}
            </Button>
            <Notice>{notice}</Notice>
            {saveError && <span className="text-[12.5px] text-destructive">{saveError}</span>}
          </div>
        </div>
      )}
    </SettingCard>
  );
}

/** Branch hours — the branch's own week, or none at all (it follows the store). */
export function BranchHoursPanel() {
  const t = useT();
  const { loading, error, branches, reload } = useBranches();
  const [branchId, setBranchId] = React.useState("");
  const branch = branches.find((b) => b.id === branchId) || branches[0];
  const [week, setWeek] = React.useState(null);
  const [saving, setSaving] = React.useState(false);
  const [notice, setNotice] = React.useState("");
  const [saveError, setSaveError] = React.useState("");

  React.useEffect(() => {
    if (!branch) return;
    const saved = branch.hours || {};
    const next = {};
    for (const day of DAYS) {
      const spec = saved[day] || null;
      next[day] = spec
        ? { closed: !!spec.closed, open: spec.open || "", close: spec.close || "" }
        : { closed: true, open: "", close: "" };
    }
    setWeek({ saved: branch.hours || null, days: next });
    setNotice("");
    setSaveError("");
  }, [branch?.id]);

  if (loading) return <Loading />;
  if (error) return <Failed message={error} />;
  if (branches.length === 0) {
    return (
      <SettingCard title={t("settings.locations.hours.title")} desc={t("settings.locations.hours.desc")}>
        <Empty>{t("settings.locations.branches.empty")}</Empty>
      </SettingCard>
    );
  }

  const write = async (payload) => {
    setSaving(true);
    setSaveError("");
    setNotice("");
    try {
      await api(`/hierarchy/locations/${branch.id}`, { method: "PATCH", body: { hours: payload } });
      setNotice(t("settings.locations.saved"));
      reload();
    } catch (e) {
      setSaveError(e?.message || t("settings.locations.saveError"));
    } finally {
      setSaving(false);
    }
  };

  const save = () => write(hoursPayload(week.days));

  const setDay = (day, patch) =>
    setWeek((w) => ({ ...w, days: { ...w.days, [day]: { ...w.days[day], ...patch } } }));

  return (
    <SettingCard title={t("settings.locations.hours.title")} desc={t("settings.locations.hours.desc")}>
      <BranchPicker
        branches={branches}
        value={branch.id}
        onChange={setBranchId}
        label={t("settings.locations.pick")}
      />
      <div className="border-t border-border pt-2.5">
        <div className="flex items-center gap-2 pb-2">
          {branch.hours ? (
            <Badge tone="primary">{t("settings.locations.hours.own")}</Badge>
          ) : (
            <Badge tone="muted">{t("settings.locations.hours.inherited")}</Badge>
          )}
        </div>
        {week && (
          <div className="space-y-1.5">
            {DAYS.map((day) => (
              <div key={day} className="flex flex-wrap items-center gap-2 text-[13px]">
                <span className="w-14 shrink-0">{t(`settings.locations.day.${day}`)}</span>
                <label className="flex items-center gap-1.5 text-[12.5px] text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={week.days[day].closed}
                    onChange={(e) => setDay(day, { closed: e.target.checked })}
                  />
                  {t("settings.locations.hours.closed")}
                </label>
                {!week.days[day].closed && (
                  <>
                    <input
                      type="time"
                      className="rounded-md border border-border bg-background px-1.5 py-1 text-[12.5px]"
                      value={week.days[day].open}
                      onChange={(e) => setDay(day, { open: e.target.value })}
                    />
                    <span className="text-muted-foreground">–</span>
                    <input
                      type="time"
                      className="rounded-md border border-border bg-background px-1.5 py-1 text-[12.5px]"
                      value={week.days[day].close}
                      onChange={(e) => setDay(day, { close: e.target.value })}
                    />
                  </>
                )}
              </div>
            ))}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3 pt-3">
          <Button size="sm" onClick={save} disabled={saving}>
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            {t("settings.locations.save")}
          </Button>
          {branch.hours && (
            <Button size="sm" variant="outline" onClick={() => write({})} disabled={saving}>
              {t("settings.locations.hours.clear")}
            </Button>
          )}
          <Notice>{notice}</Notice>
          {saveError && <span className="text-[12.5px] text-destructive">{saveError}</span>}
        </div>
        <p className="pt-2 text-[12px] text-muted-foreground">
          {t("settings.locations.hours.note")}
        </p>
      </div>
    </SettingCard>
  );
}

/** Branch staff — who may work at this branch, from the grants that already exist. */
export function BranchStaffPanel() {
  const t = useT();
  const { loading, error, branches } = useBranches();
  const [branchId, setBranchId] = React.useState("");
  const branch = branches.find((b) => b.id === branchId) || branches[0];
  const [members, setMembers] = React.useState([]);
  const [grants, setGrants] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [notice, setNotice] = React.useState("");
  const [grantError, setGrantError] = React.useState("");
  const [pick, setPick] = React.useState("");
  const [roleOverride, setRoleOverride] = React.useState("");

  const loadGrants = React.useCallback(async (id) => {
    const res = await api(`/hierarchy/locations/${id}/access`);
    setGrants(Array.isArray(res?.items) ? res.items : []);
  }, []);

  React.useEffect(() => {
    api("/users")
      .then((rows) => setMembers(Array.isArray(rows) ? rows : []))
      .catch(() => setMembers([]));
  }, []);

  React.useEffect(() => {
    if (!branch) return;
    setGrants(null);
    setNotice("");
    setGrantError("");
    loadGrants(branch.id).catch((e) => setGrantError(e?.message || t("settings.locations.staff.loadError")));
  }, [branch?.id, loadGrants, t]);

  if (loading) return <Loading />;
  if (error) return <Failed message={error} />;
  if (branches.length === 0) {
    return (
      <SettingCard title={t("settings.locations.staff.title")} desc={t("settings.locations.staff.desc")}>
        <Empty>{t("settings.locations.branches.empty")}</Empty>
      </SettingCard>
    );
  }

  const nameOf = (userId) => {
    const m = members.find((x) => x.id === userId);
    return m ? m.full_name || m.email : userId;
  };

  const grant = async () => {
    if (!pick) return;
    setBusy(true);
    setGrantError("");
    setNotice("");
    try {
      await api(`/hierarchy/locations/${branch.id}/access/${pick}`, {
        method: "PUT",
        body: { role_override: roleOverride || null },
      });
      await loadGrants(branch.id);
      setNotice(t("settings.locations.saved"));
      setPick("");
      setRoleOverride("");
    } catch (e) {
      setGrantError(e?.message || t("settings.locations.staff.grantError"));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (userId) => {
    setBusy(true);
    setGrantError("");
    setNotice("");
    try {
      await api(`/hierarchy/locations/${branch.id}/access/${userId}`, { method: "DELETE" });
      await loadGrants(branch.id);
      setNotice(t("settings.locations.saved"));
    } catch (e) {
      setGrantError(e?.message || t("settings.locations.staff.grantError"));
    } finally {
      setBusy(false);
    }
  };

  const granted = new Set((grants || []).map((g) => g.user_id));
  const candidates = members.filter((m) => !granted.has(m.id));

  return (
    <SettingCard title={t("settings.locations.staff.title")} desc={t("settings.locations.staff.desc")}>
      <BranchPicker
        branches={branches}
        value={branch.id}
        onChange={setBranchId}
        label={t("settings.locations.pick")}
      />
      <div className="border-t border-border pt-2.5">
        {grants === null && !grantError && (
          <div className="flex items-center gap-2 py-2 text-[13px] text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> {t("settings.locations.staff.loading")}
          </div>
        )}
        {grants && grants.length === 0 && <Empty>{t("settings.locations.staff.none")}</Empty>}
        {grants && grants.length > 0 && (
          <ul className="divide-y divide-border">
            {grants.map((g) => (
              <li key={g.user_id} className="flex items-center justify-between gap-3 py-2">
                <div className="min-w-0">
                  <div className="truncate text-[13px]">{nameOf(g.user_id)}</div>
                  {g.role_override && (
                    <div className="text-[12px] text-muted-foreground">{g.role_override}</div>
                  )}
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => revoke(g.user_id)}
                  disabled={busy}
                  aria-label={t("settings.locations.staff.revoke")}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </li>
            ))}
          </ul>
        )}

        {candidates.length > 0 && (
          <div className="flex flex-wrap items-end gap-2 border-t border-border pt-2.5">
            <label className="text-[13px]">
              <span className="block text-[12px] text-muted-foreground">
                {t("settings.locations.staff.member")}
              </span>
              <select
                className="mt-1 rounded-md border border-border bg-background px-2 py-1 text-[13px]"
                value={pick}
                onChange={(e) => setPick(e.target.value)}
              >
                <option value="">—</option>
                {candidates.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.full_name || m.email}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-[13px]">
              <span className="block text-[12px] text-muted-foreground">
                {t("settings.locations.staff.roleOverride")}
              </span>
              <Input
                className="mt-1 max-w-[10rem]"
                value={roleOverride}
                onChange={(e) => setRoleOverride(e.target.value)}
                placeholder="cashier"
              />
            </label>
            <Button size="sm" onClick={grant} disabled={busy || !pick}>
              <Plus className="h-3.5 w-3.5" />
              {t("settings.locations.staff.grant")}
            </Button>
          </div>
        )}

        <div className="flex items-center gap-3 pt-2">
          <Notice>{notice}</Notice>
          {grantError && <span className="text-[12.5px] text-destructive">{grantError}</span>}
        </div>
      </div>
    </SettingCard>
  );
}

/** Operating scopes — what this branch resolves to, and what it inherited. */
export function BranchScopesPanel() {
  const t = useT();
  const { loading, error, branches } = useBranches();
  const [branchId, setBranchId] = React.useState("");
  const branch = branches.find((b) => b.id === branchId) || branches[0];
  const [rows, setRows] = React.useState(null);
  const [loadError, setLoadError] = React.useState("");

  React.useEffect(() => {
    if (!branch) return;
    let alive = true;
    setRows(null);
    setLoadError("");
    api(`/settings/effective?scope=branch&scope_id=${branch.id}`)
      .then((res) => {
        if (!alive) return;
        const list = Object.values(res || {})
          .filter((r) => r?.definition?.scopes?.includes("branch"))
          .sort((a, b) => a.key.localeCompare(b.key));
        setRows(list);
      })
      .catch((e) => alive && setLoadError(e?.message || t("settings.locations.scopes.loadError")));
    return () => {
      alive = false;
    };
  }, [branch?.id, t]);

  if (loading) return <Loading />;
  if (error) return <Failed message={error} />;
  if (branches.length === 0) {
    return (
      <SettingCard title={t("settings.locations.scopes.title")} desc={t("settings.locations.scopes.desc")}>
        <Empty>{t("settings.locations.branches.empty")}</Empty>
      </SettingCard>
    );
  }

  const inheritedCount = (rows || []).filter((r) => r.is_inherited).length;
  const overriddenCount = (rows || []).filter((r) => !r.is_inherited).length;

  return (
    <SettingCard title={t("settings.locations.scopes.title")} desc={t("settings.locations.scopes.desc")}>
      <BranchPicker
        branches={branches}
        value={branch.id}
        onChange={setBranchId}
        label={t("settings.locations.pick")}
      />
      <div className="border-t border-border pt-2.5">
        {loadError && <Failed message={loadError} />}
        {rows === null && !loadError && (
          <div className="flex items-center gap-2 py-2 text-[13px] text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> {t("settings.locations.scopes.loading")}
          </div>
        )}
        {rows && (
          <>
            <div className="flex items-center gap-2 pb-2">
              <Badge tone="primary">
                {overriddenCount} {t("settings.locations.scopes.overridden")}
              </Badge>
              <Badge tone="muted">
                {inheritedCount} {t("settings.locations.scopes.inherited")}
              </Badge>
            </div>
            {rows.length === 0 ? (
              <Empty>{t("settings.locations.scopes.none")}</Empty>
            ) : (
              <ul className="divide-y divide-border">
                {rows.map((r) => (
                  <li key={r.key} className="flex items-start justify-between gap-3 py-2">
                    <div className="min-w-0">
                      <div className="truncate text-[13px]">{r.key}</div>
                      <div className="truncate text-[11.5px] text-muted-foreground">{r.definition?.domain}</div>
                    </div>
                    <div className="shrink-0 text-end">
                      <div className="num text-[12.5px]">
                        {typeof r.value === "object" ? JSON.stringify(r.value) : String(r.value)}
                      </div>
                      <div className="text-[11.5px] text-muted-foreground">
                        {r.is_inherited
                          ? t("settings.locations.scopes.fromStore")
                          : r.is_default
                            ? t("settings.locations.scopes.fromDefault")
                            : t("settings.locations.scopes.fromBranch")}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </SettingCard>
  );
}
