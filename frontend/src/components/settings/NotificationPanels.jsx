import React from "react";
import { Link } from "react-router-dom";
import { useT } from "@/lib/i18n";
import { SettingCard } from "@/components/settings/SettingsShell";

/**
 * A page whose editor lives somewhere else.
 *
 * Section 16 governs what the WORKSPACE sends. Two of its pages are not the workspace's to
 * edit: a person's own notification preferences belong to that person (section 01), and the
 * reply templates are the shop's voice already edited in section 11. Both pages therefore
 * state where the single editor is and link to it, instead of opening a second one that
 * would drift from the first.
 */
export default function ChannelLinkCard({ titleKey, descKey, to, linkKey }) {
  const t = useT();
  return (
    <SettingCard title={t(titleKey)} desc={t(descKey)}>
      <Link to={to} className="text-[13px] font-medium text-primary underline underline-offset-4">
        {t(linkKey)}
      </Link>
    </SettingCard>
  );
}
