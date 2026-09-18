"use client";

import Link from "next/link";
import { useI18n } from "@/components/public/i18n";

export function PublicFooter() {
  const { t } = useI18n();
  return (
    <footer className="fh-footer">
      <div className="fh-container fh-footer-grid">
        <div>
          <span className="fh-brand">
            <span className="fh-brand-mark" aria-hidden="true"><span>F</span></span>
            <span className="fh-brand-name">FIHRIST</span>
          </span>
          <p className="fh-footer-tag">{t.footer.tag}</p>
        </div>

        <nav aria-label={t.footer.product}>
          <h4>{t.footer.product}</h4>
          <a href="#product">{t.footer.overview}</a>
          <a href="#context">{t.nav.context}</a>
          <a href="#inbox">{t.nav.inbox}</a>
          <a href="#ai">{t.footer.aiF}</a>
          <a href="#automation">{t.footer.automationF}</a>
          <a href="#analytics">{t.footer.analyticsF}</a>
        </nav>

        <nav aria-label={t.footer.solutions}>
          <h4>{t.footer.solutions}</h4>
          {t.footer.solutionsItems.map((s) => (
            <span key={s} className="fh-footer-soon">{s}</span>
          ))}
        </nav>

        <nav aria-label={t.footer.resources}>
          <h4>{t.footer.resources}</h4>
          {t.footer.resourcesItems.map((s) => (
            <span key={s} className="fh-footer-soon">{s}</span>
          ))}
        </nav>

        <nav aria-label={t.footer.company}>
          <h4>{t.footer.company}</h4>
          <Link href="/auth/signup">{t.footer.start}</Link>
          <Link href="/auth/login">{t.footer.login}</Link>
          <h4 className="gap">{t.footer.system}</h4>
          <span className="fh-footer-soon">{t.footer.status}</span>
          <span className="fh-footer-soon">{t.footer.privacy}</span>
          <span className="fh-footer-soon">{t.footer.terms}</span>
        </nav>
      </div>

      <div className="fh-container fh-footer-bottom">
        <span>{t.footer.rights}</span>
        <span className="fh-badge">{t.brand} · {t.brandTag}</span>
      </div>
    </footer>
  );
}
