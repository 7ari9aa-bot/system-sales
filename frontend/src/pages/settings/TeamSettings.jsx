import React from "react";
import { useNavigate, useParams } from "react-router-dom";
import { KeyRound, MapPin, Send, ShieldCheck, Users, UsersRound } from "lucide-react";
import { useT } from "@/lib/i18n";
import { sectionPages } from "@/components/settings/settingsManifest";
import TeamMembersSection from "./team/TeamMembersSection";
import TeamInvitationsSection from "./team/TeamInvitationsSection";
import TeamRolesSection from "./team/TeamRolesSection";
import TeamMatrixSection from "./team/TeamMatrixSection";
import TeamGroupsSection from "./team/TeamGroupsSection";
import TeamAccessSection from "./team/TeamAccessSection";
import MissingPage from "@/components/settings/MissingPage";

/** الفريق والصلاحيات — ست صفحات، كل واحدة بمسارها.
 *
 * الصفحة دي غلاف بس: بتقرا القسم من المسار (/settings/team/<section>) وبترسمه لوحده،
 * فالصلاحيات أو نطاق الوصول بتفتح في تبويب مستقل بحالتها وعنوانها، والرجوع بيحافظ على القسم.
 *
 * الترتيب مقصود: مين موجود ← مين متدعى ← الأدوار ← المصفوفة ← المجموعات ← نطاق الوصول.
 * الأدوار بتقول إيه المتاح، والمصفوفة بتقول مين بيملكه فعلاً، والمجموعات بتجمّع الناس
 * من غير ما تدّي أي صلاحية. /settings/members القديم بيفتح صفحة الأعضاء.
 */
/** Each page's own screen, keyed by the manifest's slug. See WorkspaceSettings for why the page
 * LIST comes from the manifest and only the icon and the body live here. */
const VIEWS = {
  members: { icon: Users, render: () => <TeamMembersSection /> },
  invitations: { icon: Send, render: () => <TeamInvitationsSection /> },
  roles: { icon: ShieldCheck, render: () => <TeamRolesSection /> },
  matrix: { icon: KeyRound, render: () => <TeamMatrixSection /> },
  groups: { icon: UsersRound, render: () => <TeamGroupsSection /> },
  access: { icon: MapPin, render: () => <TeamAccessSection /> },
};

const SECTIONS = sectionPages("team").map(({ slug, labelKey }) => ({
  value: slug,
  labelKey,
  icon: VIEWS[slug]?.icon ?? Users,
  render: VIEWS[slug]?.render ?? (() => <MissingPage slug={slug} />),
}));

export const TEAM_SECTION_SLUGS = SECTIONS.map((section) => section.value);

/** القسم المطلوب، أو «الأعضاء» لو المسار بلا قسم أو بقسم غير معروف. */
export function resolveTeamSection(slug) {
  return SECTIONS.find((section) => section.value === slug) ?? SECTIONS[0];
}

export default function TeamSettings() {
  const { section } = useParams();
  const navigate = useNavigate();
  const t = useT();
  const active = resolveTeamSection(section);

  return (
    <div>
      <nav
        aria-label={t("team.sectionLabel")}
        role="tablist"
        className="mb-4 flex w-full flex-wrap justify-start gap-1 border-b border-border"
      >
        {SECTIONS.map((item) => {
          const Icon = item.icon;
          const isActive = item.value === active.value;
          return (
            <button
              key={item.value}
              type="button"
              role="tab"
              aria-selected={isActive}
              aria-current={isActive ? "page" : undefined}
              onClick={() => navigate(`/settings/team/${item.value}`)}
              className={`flex items-center gap-1.5 rounded-t-lg px-3 py-2 text-[12.5px] font-medium transition-colors ${
                isActive
                  ? "border-b-2 border-primary text-primary"
                  : "border-b-2 border-transparent text-muted-foreground hover:bg-muted"
              }`}
            >
              <Icon className="h-4 w-4" />
              {t(item.labelKey)}
            </button>
          );
        })}
      </nav>
      <div data-section={active.value}>{active.render()}</div>
    </div>
  );
}
