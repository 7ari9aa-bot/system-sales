import { getTokens } from "@/lib/api";

/** Which workspace a settings screen is acting on.
 *
 * One answer, or none. Auth lives in an httpOnly session cookie now, so the JWT claim is read
 * only when the tokens are actually exposed (kept for the desktop shell); otherwise the answer is
 * the single membership the account has. With more than one membership the screens get `null` and
 * disable their writes rather than guess — writing a shop name, a currency or an offboarding
 * export into the WRONG shop is not a mistake anyone can undo from the UI.
 */
export function activeTenantId(user) {
  try {
    const payload = getTokens()?.access_token?.split(".")[1];
    const normalized = payload?.replace(/-/g, "+").replace(/_/g, "/");
    const tokenTenant = normalized
      ? JSON.parse(window.atob(normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "="))).tenant_id
      : null;
    if (tokenTenant) return tokenTenant;
  } catch {
    // a token this browser cannot decode is not a reason to act on a guess
  }
  return user?.tenants?.length === 1 ? user.tenants[0].id : null;
}

/** The membership row for the workspace above: `{ id, name, slug, role_code }`, or null. */
export function activeTenant(user) {
  const id = activeTenantId(user);
  if (!id) return null;
  return user?.tenants?.find((item) => item.id === id) || null;
}
