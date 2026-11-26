/** Who may see the Developers & API section.
 *
 * The map's rule for section 20 is that it is hidden from ordinary users and shown only to
 * developer / integration roles. That is a NAVIGATION and ROUTE decision, not a cosmetic one:
 * a cashier has no reason to read the webhook delivery log or the request ceilings, and the
 * screen must not be reachable by typing its address either.
 *
 * The answer comes from the membership the account actually holds for the active workspace
 * (`activeTenant`), never from a hardcoded list of emails or a "developer" flag that no table
 * stores. `staff` and `cashier` are the two roles the seeded matrix gives no settings grants
 * to, so they are the two that do not see this section.
 *
 * This is not the authorization boundary — the server gates every endpoint behind it with
 * `settings:read`, and a hidden screen is never a permission. It decides what a person is
 * shown, which is what the map asks for.
 */
import { activeTenant } from "@/lib/activeTenant";

export const DEVELOPER_ROLES = ["owner", "admin", "manager"];

export function canSeeDevelopers(user) {
  const membership = activeTenant(user);
  if (!membership) return false;
  return DEVELOPER_ROLES.includes(membership.role_code);
}
