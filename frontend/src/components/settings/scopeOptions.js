import { apiCached } from "@/lib/api";

/**
 * The entities a setting can be scoped to, by name.
 *
 * The scope selector used to ask the owner to paste a UUID: an id the settings page never
 * showed anywhere else, so in practice only the tenant scope was ever used. Each scope now
 * resolves to a labelled list of the tenant's own rows, and the id is taken from the pick.
 */

const label = (row, fallback) => row?.name || row?.display_name || row?.title || fallback;

/** Workspaces are the root of the branch chain, so branches are listed per workspace. */
async function loadBranches() {
  const workspaces = await apiCached("/hierarchy/workspaces", { ttlMs: 0 });
  const items = workspaces?.items ?? [];
  const groups = await Promise.all(
    items.map(async (workspace) => {
      try {
        const locations = await apiCached(
          `/hierarchy/workspaces/${workspace.id}/locations`,
          { ttlMs: 0 },
        );
        return (locations?.items ?? []).map((row) => ({
          id: row.id,
          name: label(row, row.id),
          hint: label(workspace, ""),
        }));
      } catch {
        return [];
      }
    }),
  );
  return groups.flat();
}

const LOADERS = {
  workspace: async () => {
    const rows = await apiCached("/hierarchy/workspaces", { ttlMs: 0 });
    return (rows?.items ?? []).map((row) => ({ id: row.id, name: label(row, row.id) }));
  },
  branch: loadBranches,
  warehouse: async () => {
    const rows = await apiCached("/warehouses", { ttlMs: 0 });
    return (Array.isArray(rows) ? rows : (rows?.items ?? [])).map((row) => ({
      id: row.id,
      name: label(row, row.id),
    }));
  },
  pos_profile: async () => {
    const rows = await apiCached("/pos/profiles", { ttlMs: 0 });
    return (Array.isArray(rows) ? rows : (rows?.items ?? [])).map((row) => ({
      id: row.id,
      name: label(row, row.id),
    }));
  },
  register: async () => {
    const rows = await apiCached("/pos/registers", { ttlMs: 0 });
    return (Array.isArray(rows) ? rows : (rows?.items ?? [])).map((row) => ({
      id: row.id,
      name: label(row, row.id),
      hint: row.profile_name || "",
    }));
  },
  channel: async () => {
    const rows = await apiCached("/integrations", { ttlMs: 0 });
    // Only channel accounts are valid scopes: the backend refuses any other integration kind.
    return (Array.isArray(rows) ? rows : []).map((row) => ({
      id: row.id,
      name: row.display_name || row.provider || row.id,
      hint: row.kind && row.kind !== "channel" ? row.kind : "",
      disabled: row.kind !== "channel",
    }));
  },
  user: async () => {
    const rows = await apiCached("/users", { ttlMs: 0 });
    return (Array.isArray(rows) ? rows : (rows?.items ?? [])).map((row) => ({
      id: row.id,
      name: row.full_name || row.email || row.id,
      hint: row.email || "",
    }));
  },
};

/** Scopes that need the owner to choose one of their rows. */
export const SCOPES_WITH_PICKER = Object.keys(LOADERS);

export async function loadScopeOptions(scope) {
  const loader = LOADERS[scope];
  if (!loader) return [];
  const rows = await loader();
  return rows.filter((row) => row && row.id);
}
