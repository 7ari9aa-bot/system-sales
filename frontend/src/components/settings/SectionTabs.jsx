import React from "react";
import { Link } from "react-router-dom";
import { useT } from "@/lib/i18n";
import { sectionPages } from "@/components/settings/settingsManifest";

/**
 * The tab strip of a section, generated from the manifest.
 *
 * Sections that own their screen (store, locations, security, …) render their own strip inside
 * `SettingsSection`; the channel pages are separate route components, so they use this. Both
 * read `sectionPages()`, which is the point: the tabs a person sees are the manifest's pages,
 * so a page cannot exist in the router and be unreachable from the navigation.
 */
export default function SectionTabs({ section, active, ariaLabel }) {
  const t = useT();
  const pages = sectionPages(section);
  if (pages.length < 2) return null;
  return (
    <nav
      aria-label={ariaLabel}
      role="tablist"
      className="mb-4 flex w-full flex-wrap justify-start gap-1 border-b border-border"
    >
      {pages.map(({ slug, labelKey }) => {
        const isActive = slug === active;
        return (
          <Link
            key={slug}
            to={`/settings/${section}/${slug}`}
            role="tab"
            aria-selected={isActive}
            aria-current={isActive ? "page" : undefined}
            className={
              isActive
                ? "border-b-2 border-primary px-3 py-2 text-[12.5px] font-medium text-primary"
                : "border-b-2 border-transparent px-3 py-2 text-[12.5px] text-muted-foreground hover:bg-muted hover:text-foreground"
            }
          >
            {t(labelKey, slug)}
          </Link>
        );
      })}
    </nav>
  );
}
