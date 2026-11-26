import React from "react";
import { Loader2, MapPin, UserMinus, UserPlus } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import { Button } from "@/components/ui/button";

/** Access scope: which branch each person may reach.
 *
 * This is the page where access is actually narrowed, and it writes the real
 * ``user_location_access`` rows through /hierarchy/locations/{id}/access. The role
 * says what someone may do anywhere; this says where. A person with no grant here
 * is not restricted to nothing — the tenant-wide role still applies — so the page
 * states what a grant adds rather than implying it is the only door.
 *
 * Warehouses and registers are NOT here: a branch is a location, a warehouse is
 * stock and a register is a till, and the map keeps them on different pages.
 */
export default function TeamAccessSection() {
  const t = useT();
  const [locations, setLocations] = React.useState(null);
  const [roster, setRoster] = React.useState([]);
  const [open, setOpen] = React.useState("");
  const [grants, setGrants] = React.useState({});
  const [pick, setPick] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    Promise.all([api("/hierarchy/locations"), api("/users")])
      .then(([list, people]) => {
        if (!alive) return;
        setLocations(list?.items || []);
        setRoster(Array.isArray(people) ? people : []);
      })
      .catch((failure) => {
        if (!alive) return;
        setLocations([]);
        setError(failure?.message || t("team.loadFailed"));
      });
    return () => {
      alive = false;
    };
  }, [t]);

  async function openLocation(location) {
    if (open === location.id) {
      setOpen("");
      return;
    }
    setOpen(location.id);
    if (grants[location.id]) return;
    try {
      const list = await api(`/hierarchy/locations/${location.id}/access`);
      setGrants((current) => ({ ...current, [location.id]: list?.items || [] }));
    } catch (failure) {
      setError(failure?.message || t("team.loadFailed"));
    }
  }

  async function refresh(locationId) {
    const list = await api(`/hierarchy/locations/${locationId}/access`);
    setGrants((current) => ({ ...current, [locationId]: list?.items || [] }));
  }

  async function grant(location) {
    if (!pick || busy) return;
    setBusy(true);
    try {
      await api(`/hierarchy/locations/${location.id}/access/${pick}`, {
        method: "PUT",
        body: { role_override: null },
      });
      setPick("");
      await refresh(location.id);
    } catch (failure) {
      setError(failure?.message || t("team.access.grantFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function revoke(location, person) {
    setBusy(true);
    try {
      await api(`/hierarchy/locations/${location.id}/access/${person.user_id || person.id}`, {
        method: "DELETE",
      });
      await refresh(location.id);
    } catch (failure) {
      setError(failure?.message || t("team.access.revokeFailed"));
    } finally {
      setBusy(false);
    }
  }

  const nameOf = (id) => {
    const person = roster.find((item) => item.id === id);
    return person?.full_name || person?.email || id;
  };

  return (
    <SettingsShell title={t("team.access.title")} desc={t("team.access.desc")}>
      {error && (
        <div role="alert" className="mb-3 rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
          {error}
        </div>
      )}
      {locations === null && !error && (
        <p className="inline-flex items-center gap-2 text-[12.5px] text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          {t("team.loading")}
        </p>
      )}
      {locations?.length === 0 && (
        <p className="text-[12.5px] text-muted-foreground">{t("team.access.noLocations")}</p>
      )}
      {(locations || []).length > 0 && (
        <SettingCard title={t("team.access.byLocation")} desc={t("team.access.byLocation.desc")}>
          {(locations || []).map((location) => (
            <div key={location.id} className="border-b border-border last:border-0">
              <SettingRow label={location.name} desc={location.code} last>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => openLocation(location)}
                  data-testid={`access-open-${location.id}`}
                >
                  <MapPin className="me-1.5 h-3.5 w-3.5" />
                  {t("team.access.manage")}
                </Button>
              </SettingRow>
              {open === location.id && (
                <div className="pb-3 ps-1">
                  {(grants[location.id] || []).map((row) => (
                    <div
                      key={row.user_id || row.id}
                      className="flex items-center justify-between gap-3 border-b border-border py-1.5 last:border-0"
                    >
                      <span className="text-[12.5px]">{nameOf(row.user_id || row.id)}</span>
                      <button
                        type="button"
                        aria-label={t("team.access.revoke", { name: nameOf(row.user_id || row.id) })}
                        disabled={busy}
                        onClick={() => revoke(location, row)}
                        className="h-7 w-7 grid place-items-center rounded-lg text-muted-foreground hover:bg-surface disabled:opacity-50"
                      >
                        <UserMinus className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                  {(grants[location.id] || []).length === 0 && (
                    <p className="py-1.5 text-[12px] text-muted-foreground">{t("team.access.none")}</p>
                  )}
                  <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                    <select
                      value={pick}
                      onChange={(event) => setPick(event.target.value)}
                      aria-label={t("team.access.pickPerson")}
                      className="h-9 rounded-md border border-input bg-background px-2 text-[12.5px]"
                    >
                      <option value="">{t("team.access.pickPerson")}</option>
                      {roster
                        .filter(
                          (person) =>
                            !(grants[location.id] || []).some(
                              (row) => (row.user_id || row.id) === person.id,
                            ),
                        )
                        .map((person) => (
                          <option key={person.id} value={person.id}>
                            {person.full_name || person.email}
                          </option>
                        ))}
                    </select>
                    <Button
                      type="button"
                      size="sm"
                      disabled={!pick || busy}
                      onClick={() => grant(location)}
                      className="gap-1.5"
                    >
                      <UserPlus className="h-4 w-4" />
                      {t("team.access.grant")}
                    </Button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </SettingCard>
      )}
      <p className="mt-4 text-[11.5px] leading-relaxed text-muted-foreground">{t("team.access.note")}</p>
    </SettingsShell>
  );
}
