import React from "react";
import { Link } from "react-router-dom";
import {
  ArrowUpRight,
  CreditCard,
  MessageSquare,
  ShieldCheck,
  Store,
  Users,
  UserRound,
  Sparkles,
  ScanLine,
  ScrollText,
  Gauge,
  Database,
} from "lucide-react";
import { useT } from "@/lib/i18n";
import SettingsShell from "@/components/settings/SettingsShell";

const GROUPS = [
  {
    titleKey: "settings.overview.account",
    descriptionKey: "settings.overview.profileHint",
    icon: UserRound,
    links: [
      { to: "/settings", key: "settings.nav.profile", icon: UserRound },
      { to: "/settings/security", key: "settings.nav.security", icon: ShieldCheck },
      { to: "/settings/members", key: "settings.nav.members", icon: Users },
    ],
  },
  {
    titleKey: "settings.group.store",
    descriptionKey: "settings.overview.storeHint",
    icon: Store,
    links: [
      { to: "/settings/workspace", key: "settings.nav.workspace", icon: Store },
      { to: "/settings/policies", key: "settings.nav.policies", icon: ScrollText },
    ],
  },
  {
    titleKey: "settings.overview.operations",
    descriptionKey: "settings.overview.operationsHint",
    icon: MessageSquare,
    links: [
      { to: "/settings/channels", key: "settings.nav.channels", icon: MessageSquare },
      { to: "/settings/ai", key: "settings.nav.ai", icon: Sparkles },
      { to: "/settings/pos", key: "settings.nav.pos", icon: ScanLine },
    ],
  },
  {
    titleKey: "settings.overview.plan",
    descriptionKey: "settings.overview.planHint",
    icon: CreditCard,
    links: [
      { to: "/settings/billing", key: "settings.nav.billing", icon: CreditCard },
      { to: "/settings/usage", key: "settings.nav.usage", icon: Gauge },
      { to: "/settings/danger", key: "settings.nav.danger", icon: Database },
    ],
  },
];

function SettingsGroup({ group }) {
  const t = useT();
  const GroupIcon = group.icon;

  return (
    <section className="flex min-w-0 flex-col rounded-2xl border border-border bg-card p-5 transition-colors hover:border-primary/30">
      <div className="flex items-start gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
          <GroupIcon className="size-5" aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <h2 className="font-display text-[15px] font-semibold">{t(group.titleKey)}</h2>
          <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">{t(group.descriptionKey)}</p>
        </div>
      </div>
      <nav className="mt-4 flex flex-col border-t border-border pt-2" aria-label={t(group.titleKey)}>
        {group.links.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.to}
              to={item.to}
              className="group flex min-h-10 items-center gap-2.5 rounded-lg px-2 text-[13px] font-medium transition-colors hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Icon className="size-4 shrink-0 text-muted-foreground group-hover:text-primary" aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate">{t(item.key)}</span>
              <ArrowUpRight className="size-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
            </Link>
          );
        })}
      </nav>
    </section>
  );
}

export default function SettingsOverview() {
  const t = useT();

  return (
    <SettingsShell title={t("settings.overview.title")} subtitle={t("settings.overview.desc")}>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {GROUPS.map((group) => <SettingsGroup key={group.titleKey} group={group} />)}
      </div>
    </SettingsShell>
  );
}
