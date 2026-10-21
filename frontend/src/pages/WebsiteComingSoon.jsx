import React from "react";
import { Link } from "react-router-dom";
import { Globe, Lock } from "lucide-react";
import { PageHeader, SectionCard, Badge } from "@/components/dashboard/ui";
import { useT } from "@/lib/i18n";

/**
 * «My Website» is locked for the first release: the website system is not finished.
 * The real screen (pages/Website.jsx: provisioning, Studio SSO, publishing) is kept untouched
 * and is NOT routed, so switching the feature on later is a one-line change in App.jsx.
 */
export default function WebsiteComingSoon() {
  const t = useT();
  return (
    <div className="space-y-6">
      <PageHeader title={t("nav.website")} />
      <SectionCard>
        <div className="flex flex-col items-center text-center gap-4 py-12 px-4">
          <div className="relative h-16 w-16 rounded-2xl bg-primary/10 text-primary flex items-center justify-center">
            <Globe className="h-8 w-8" aria-hidden="true" />
            <span className="absolute -bottom-1.5 -end-1.5 h-7 w-7 rounded-full bg-background border border-border flex items-center justify-center">
              <Lock className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
            </span>
          </div>
          <Badge>{t("website.soon.badge")}</Badge>
          <h2 className="text-lg font-semibold text-foreground">{t("website.soon.title")}</h2>
          <p className="max-w-md text-sm text-muted-foreground leading-relaxed">{t("website.soon.body")}</p>
          <Link to="/dashboard" className="text-sm font-medium text-primary hover:underline">
            {t("website.soon.back")}
          </Link>
        </div>
      </SectionCard>
    </div>
  );
}
