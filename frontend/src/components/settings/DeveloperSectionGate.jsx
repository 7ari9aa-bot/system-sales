/** The route guard for section 20, Developers & API.
 *
 * The map says this section is hidden from ordinary users and shown only to developer /
 * integration roles. Hiding the sidebar entry is not enough: the address is guessable, and a
 * cashier who types `/settings/developers/webhooks` must not be handed the shop's webhook
 * delivery log. So the guard sits on the ROUTE, in one place, instead of inside every page.
 *
 * It reads the role of the person's membership in the active workspace (`canSeeDevelopers`)
 * and renders the section or an explanation. The server remains the authority: every endpoint
 * behind these pages is gated by `settings:read`, so a hidden screen is a convenience, never a
 * permission.
 */
import React from "react";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/AuthContext";
import SettingsShell from "@/components/settings/SettingsShell";
import { canSeeDevelopers } from "@/lib/developerAccess";

export default function DeveloperSectionGate({ children }) {
  const { user } = useAuth();
  const { lang } = useI18n();
  const isAr = lang === "ar";

  if (canSeeDevelopers(user)) return children;

  return (
    <SettingsShell
      title={isAr ? "المطورون وواجهات API" : "Developers & API"}
      subtitle={
        isAr
          ? "هذا القسم متاح لأدوار المالك والمدير فقط."
          : "This section is available to owner, admin and manager roles only."
      }
    >
      <div
        data-testid="developer-section-denied"
        className="py-8 text-center text-[13px] text-muted-foreground"
      >
        {isAr
          ? "لا تملك صلاحية الوصول إلى هذا القسم في مساحة العمل الحالية."
          : "You do not have access to this section in the current workspace."}
      </div>
    </SettingsShell>
  );
}
