import React from "react";
import { Loader2, Plus, Trash2, UserMinus, UserPlus } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** Teams and departments: groupings of people, and nothing more.
 *
 * The page says out loud that a team grants nothing, because the expectation it has
 * to defeat is the opposite one: a person who joins "فريق المخزن" will assume they can
 * now see the warehouse. Permissions come from the role and from the access scope, and
 * both of those pages are one tab away.
 */
export default function TeamGroupsSection() {
  const t = useT();
  const [teams, setTeams] = React.useState(null);
  const [roster, setRoster] = React.useState([]);
  const [openTeam, setOpenTeam] = React.useState("");
  const [members, setMembers] = React.useState({});
  const [name, setName] = React.useState("");
  const [pick, setPick] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const [list, people] = await Promise.all([api("/teams"), api("/users")]);
      setTeams(list?.items || []);
      setRoster(Array.isArray(people) ? people : []);
      setError("");
    } catch (failure) {
      setTeams([]);
      setError(failure?.message || t("team.loadFailed"));
    }
  }, [t]);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function loadMembers(teamId) {
    if (openTeam === teamId) {
      setOpenTeam("");
      return;
    }
    setOpenTeam(teamId);
    if (members[teamId]) return;
    try {
      const list = await api(`/teams/${teamId}/members`);
      setMembers((current) => ({ ...current, [teamId]: list?.items || [] }));
    } catch (failure) {
      setError(failure?.message || t("team.loadFailed"));
    }
  }

  async function create(event) {
    event.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      await api("/teams", { method: "POST", body: { name: name.trim() } });
      setName("");
      await load();
    } catch (failure) {
      setError(failure?.message || t("team.groups.createFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function removeTeam(team) {
    if (!window.confirm(t("team.groups.confirmDelete", { name: team.name }))) return;
    setBusy(true);
    try {
      await api(`/teams/${team.id}`, { method: "DELETE" });
      await load();
    } catch (failure) {
      setError(failure?.message || t("team.groups.deleteFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function addMember(team) {
    if (!pick || busy) return;
    setBusy(true);
    try {
      await api(`/teams/${team.id}/members/${pick}`, { method: "PUT" });
      const list = await api(`/teams/${team.id}/members`);
      setMembers((current) => ({ ...current, [team.id]: list?.items || [] }));
      setPick("");
      await load();
    } catch (failure) {
      setError(failure?.message || t("team.groups.memberFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function dropMember(team, person) {
    setBusy(true);
    try {
      await api(`/teams/${team.id}/members/${person.id}`, { method: "DELETE" });
      const list = await api(`/teams/${team.id}/members`);
      setMembers((current) => ({ ...current, [team.id]: list?.items || [] }));
      await load();
    } catch (failure) {
      setError(failure?.message || t("team.groups.memberFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <SettingsShell title={t("team.groups.title")} desc={t("team.groups.desc")}>
      {error && (
        <div role="alert" className="mb-3 rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
          {error}
        </div>
      )}

      <SettingCard title={t("team.groups.new")} desc={t("team.groups.new.desc")}>
        <form onSubmit={create} className="flex flex-col gap-2 py-2 sm:flex-row">
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={120}
            placeholder={t("team.groups.namePlaceholder")}
            aria-label={t("team.groups.name")}
            data-testid="team-name"
          />
          <Button type="submit" disabled={busy || !name.trim()} className="shrink-0 gap-1.5">
            <Plus className="h-4 w-4" />
            {t("team.groups.create")}
          </Button>
        </form>
      </SettingCard>

      <div className="mt-6">
        <SettingCard title={t("team.groups.list")} desc={t("team.groups.list.desc")}>
          {teams === null && (
            <p className="inline-flex items-center gap-2 py-2 text-[12.5px] text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {t("team.loading")}
            </p>
          )}
          {teams?.length === 0 && (
            <p className="py-2 text-[12.5px] text-muted-foreground">{t("team.groups.none")}</p>
          )}
          {(teams || []).map((team, index) => (
            <div key={team.id} className="border-b border-border last:border-0">
              <SettingRow
                label={team.name}
                desc={t("team.groups.memberCount", { count: team.member_count })}
                last
              >
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => loadMembers(team.id)}
                    data-testid={`team-open-${team.id}`}
                  >
                    {t("team.groups.manage")}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={t("team.groups.delete", { name: team.name })}
                    disabled={busy}
                    onClick={() => removeTeam(team)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </SettingRow>
              {openTeam === team.id && (
                <div className="pb-3 ps-1">
                  {(members[team.id] || []).map((person) => (
                    <div
                      key={person.id}
                      className="flex items-center justify-between gap-3 border-b border-border py-1.5 last:border-0"
                    >
                      <div className="min-w-0">
                        <div className="text-[12.5px] font-medium truncate">{person.full_name}</div>
                        <div className="text-[11px] text-muted-foreground truncate">{person.email}</div>
                      </div>
                      <button
                        type="button"
                        aria-label={t("team.groups.removeMember", { name: person.full_name })}
                        disabled={busy}
                        onClick={() => dropMember(team, person)}
                        className="h-7 w-7 grid place-items-center rounded-lg text-muted-foreground hover:bg-surface disabled:opacity-50"
                      >
                        <UserMinus className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                  {(members[team.id] || []).length === 0 && (
                    <p className="py-1.5 text-[12px] text-muted-foreground">{t("team.groups.noMembers")}</p>
                  )}
                  <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                    <select
                      value={pick}
                      onChange={(event) => setPick(event.target.value)}
                      aria-label={t("team.groups.pickPerson")}
                      className="h-9 rounded-md border border-input bg-background px-2 text-[12.5px]"
                    >
                      <option value="">{t("team.groups.pickPerson")}</option>
                      {roster
                        .filter((person) => !(members[team.id] || []).some((item) => item.id === person.id))
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
                      onClick={() => addMember(team)}
                      className="gap-1.5"
                    >
                      <UserPlus className="h-4 w-4" />
                      {t("team.groups.addMember")}
                    </Button>
                  </div>
                </div>
              )}
              {index === (teams || []).length - 1 ? null : null}
            </div>
          ))}
        </SettingCard>
      </div>

      <p className="mt-4 text-[11.5px] leading-relaxed text-muted-foreground">{t("team.groups.note")}</p>
    </SettingsShell>
  );
}
