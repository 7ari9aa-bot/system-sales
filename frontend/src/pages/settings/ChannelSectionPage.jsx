/** The three cross-channel pages of section 12, each one addressable on its own URL.
 *
 * `Connected channels` and the per-channel pages are the existing ChannelsSettings screen, so
 * this file only adds what that screen does not answer: what is syncing, which integrations are
 * not channels, and the health of everything at once.
 */
import React from "react";
import { useI18n } from "@/lib/i18n";
import SectionTabs from "@/components/settings/SectionTabs";
import SettingsShell from "@/components/settings/SettingsShell";
import {
  ConnectionHealthPanel,
  DataSyncPanel,
  ExternalIntegrationsPanel,
} from "@/components/settings/ChannelSectionPanels";

const PANELS = {
  "data-sync": DataSyncPanel,
  "external-integrations": ExternalIntegrationsPanel,
  "connection-health": ConnectionHealthPanel,
};

const TITLES = {
  "data-sync": ["settings.channels.dataSync.title", "settings.channels.dataSync.desc"],
  "external-integrations": ["settings.channels.external.title", "settings.channels.external.desc"],
  "connection-health": ["settings.channels.health.title", "settings.channels.health.desc"],
};

export default function ChannelSectionPage({ page }) {
  const { isAr } = useI18n();
  const Panel = PANELS[page] || DataSyncPanel;
  const [titleKey, descKey] = TITLES[page] || TITLES["data-sync"];
  const titles = {
    "settings.channels.dataSync.title": isAr ? "مزامنة البيانات" : "Data sync",
    "settings.channels.dataSync.desc": isAr
      ? "ما الذي يصل من كل قناة ومتى آخر حدث"
      : "What arrives from each channel and when the last event came",
    "settings.channels.external.title": isAr ? "التكاملات الخارجية" : "External integrations",
    "settings.channels.external.desc": isAr
      ? "الاتصالات التي ليست قنوات رسائل"
      : "The connections that are not messaging channels",
    "settings.channels.health.title": isAr ? "صحة الاتصال" : "Connection health",
    "settings.channels.health.desc": isAr
      ? "حالة كل اتصال وشهاداته في مكان واحد"
      : "Every connection's state and verification in one place",
  };

  return (
    <SettingsShell title={titles[titleKey]} subtitle={titles[descKey]}>
      <SectionTabs section="channels" active={page} ariaLabel={isAr ? "صفحات القنوات" : "Channel pages"} />
      <Panel />
    </SettingsShell>
  );
}
