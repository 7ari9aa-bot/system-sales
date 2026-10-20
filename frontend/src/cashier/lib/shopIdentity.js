/**
 * What the app really knows about the shop. The backend keeps only the tenant name (GET /auth/me ->
 * tenants[]); address, phone, tax id and branch are not stored anywhere yet, so they are never
 * invented here. Everything that is unknown stays empty.
 */
export function shopFromUser(user) {
  const t = Array.isArray(user?.tenants) ? user.tenants[0] : null;
  return { name: String(t?.name ?? "").trim() };
}
