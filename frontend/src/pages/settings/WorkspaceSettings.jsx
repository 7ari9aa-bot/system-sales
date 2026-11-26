import React from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Building2, Gauge, ShieldCheck, SlidersHorizontal, Users } from "lucide-react";
import { useT } from "@/lib/i18n";
import WorkspaceOverviewSection from "./workspace/WorkspaceOverviewSection";
import WorkspaceDataSection from "./workspace/WorkspaceDataSection";
import WorkspaceOwnershipSection from "./workspace/WorkspaceOwnershipSection";
import WorkspaceSwitchSection from "./workspace/WorkspaceSwitchSection";
import WorkspaceDefaultsSection from "./workspace/WorkspaceDefaultsSection";

/** مساحة العمل — خمس صفحات، كل واحدة بمسارها.
 *
 * الصفحة دي غلاف بس: بتقرا القسم من المسار (/settings/workspace/<section>) وبترسمه لوحده،
 * فالملكية أو التبديل بين المساحات بتفتح في تبويب مستقل بحالته وعنوانه، والرجوع بيحافظ على القسم.
 *
 * مساحة العمل هنا هي الحاوية التنظيمية اللي بتضم النشاط والأعضاء والإعدادات المشتركة — مش
 * المتجر نفسه. ولازم نفرّقها عن «workspace» الداخلي في الهيكل التنظيمي (tenant → workspace →
 * location) اللي بيتدار من صفحة الفروع، رغم إن الاتنين بنفس الاسم.
 */
const SECTIONS = [
  { value: "overview", labelKey: "workspace.tab.overview", icon: Gauge, render: () => <WorkspaceOverviewSection /> },
  { value: "data", labelKey: "workspace.tab.data", icon: Building2, render: () => <WorkspaceDataSection /> },
  {
    value: "ownership",
    labelKey: "workspace.tab.ownership",
    icon: ShieldCheck,
    render: () => <WorkspaceOwnershipSection />,
  },
  { value: "switch", labelKey: "workspace.tab.switch", icon: Users, render: () => <WorkspaceSwitchSection /> },
  {
    value: "defaults",
    labelKey: "workspace.tab.defaults",
    icon: SlidersHorizontal,
    render: () => <WorkspaceDefaultsSection />,
  },
];

export const WORKSPACE_SECTION_SLUGS = SECTIONS.map((section) => section.value);

/** القسم المطلوب، أو «نظرة عامة» لو المسار بلا قسم أو بقسم غير معروف. */
export function resolveWorkspaceSection(slug) {
  return SECTIONS.find((section) => section.value === slug) ?? SECTIONS[0];
}

export default function WorkspaceSettings() {
  const { section } = useParams();
  const navigate = useNavigate();
  const t = useT();
  const active = resolveWorkspaceSection(section);

  return (
    <div>
      <nav
        aria-label={t("workspace.sectionLabel")}
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
              onClick={() => navigate(`/settings/workspace/${item.value}`)}
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
