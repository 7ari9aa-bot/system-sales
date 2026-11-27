/**
 * What the signed-in member may do in the Settings Center, and where that answer comes from.
 *
 * The Center used to answer with the ROLE NAME alone (`visibleGroupsFor(roleCode)` in the
 * layout, `canSeeDevelopers` for section 20). A role name is not a grant: the seeded matrix
 * gives `staff` no `settings:*` code at all and `manager` no `settings:write`, so the
 * navigation offered twenty sections to an account the API answers 403 to, and a manager could
 * type a value into a field the save would refuse.
 *
 * `/roles/me` answers with the caller's own codes, computed by the same dependency
 * (`TenantContext.permission_codes`) that every settings route is gated by. So the screen and
 * the server read ONE fact. This module is the client half: one cached read, one rule.
 *
 * Not the authorization boundary, and must never be treated as one: the server still refuses
 * every request on its own. Hiding a control is courtesy; the 403 is the rule.
 */
import { api } from "@/lib/api";

export const SETTINGS_READ = "settings:read";
export const SETTINGS_WRITE = "settings:write";
export const SETTINGS_READ_SENSITIVE = "settings:read_sensitive";

/** `{ roleCode, permissions: Set<string> }` — the shape every consumer reads. */
function shape(payload) {
  return {
    roleCode: payload?.role_code ?? null,
    permissions: new Set(Array.isArray(payload?.permissions) ? payload.permissions : []),
  };
}

let inFlight = null;
let resolved = null;

/**
 * The caller's access, fetched at most once per page load.
 *
 * Twenty sections mounting at once must not be twenty requests, and a section switch must not
 * re-ask: the grant cannot change inside one page load without a re-login.
 */
export function loadSettingsAccess() {
  if (resolved) return Promise.resolve(resolved);
  if (inFlight) return inFlight;
  inFlight = api("/roles/me")
    .then((payload) => {
      resolved = shape(payload);
      return resolved;
    })
    .catch((failure) => {
      // A failure is NOT "no permissions": that would hide the whole Center on a flaky
      // network. Answer `null` and let the caller decide (it falls back to the role gate and
      // the server's own 403s).
      inFlight = null;
      throw failure;
    });
  return inFlight;
}

/** Test seam: forget the cached answer. */
export function resetSettingsAccess() {
  inFlight = null;
  resolved = null;
}

/**
 * The one rule: may this member SEE this section?
 *
 * `section.roles` is the older, narrower gate the map states for section 20 (developer roles
 * only) and it still applies — it is about WHO the person is, which a permission code cannot
 * express. Everything else is the settings grant.
 *
 * Returns `null` while the answer is still unknown, so a caller can render "checking" instead
 * of guessing either way.
 */
export function canSeeSection(access, section) {
  if (!access) return null;
  // The personal screens (My account) edit the signed-in person, not the shop: they are never
  // behind a shop grant, or a staff member could not change their own password.
  if (section?.personal) return true;
  if (section?.roles && !section.roles.includes(access.roleCode)) return false;
  return access.permissions.has(section?.permission || SETTINGS_READ);
}

/** May this member WRITE settings in the active tenant? */
export function canWriteSettings(access) {
  if (!access) return null;
  return access.permissions.has(SETTINGS_WRITE);
}

/**
 * The sidebar, filtered by the grant.
 *
 * A pure function of (groups, canSee) so the rule can be tested without a browser, and so the
 * layout keeps no opinion of its own: it draws whatever this returns.
 */
export function visibleNavGroups(groups, canSee) {
  return groups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => canSee(item) !== false),
    }))
    .filter((group) => group.items.length > 0);
}
