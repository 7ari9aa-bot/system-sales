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
          <span className="fh-badge" style={{ marginTop: ".8rem" }}>{t.footer.earlyAccess}</span>
        </div>

        <nav aria-label={t.footer.product}>
          <h4>{t.footer.product}</h4>
          <Link href="/product">{t.nav.product}</Link>
          <Link href="/context">{t.nav.context}</Link>
          <Link href="/conversations">{t.nav.inbox}</Link>
          <Link href="/assistant">{t.nav.ai}</Link>
          <Link href="/automation">{t.nav.automation}</Link>
          <Link href="/pricing">{t.nav.pricing}</Link>
          <Link href="/security">{t.nav.security}</Link>
        </nav>

        <nav aria-label={t.footer.system}>
          <h4>{t.footer.system}</h4>
          <Link href="/auth/signup">{t.nav.start}</Link>
          <Link href="/auth/login">{t.nav.login}</Link>
          <span className="fh-footer-soon">{t.footer.status}</span>
        </nav>

        <nav aria-label={t.footer.privacy}>
          <h4>{t.footer.privacy}</h4>
          <Link href="/privacy">{t.footer.privacy}</Link>
          <Link href="/terms">{t.footer.terms}</Link>
        </nav>
      </div>

      <div className="fh-container fh-footer-bottom">
        <span>{t.footer.rights}</span>
        <span className="fh-badge">{t.brand} · {t.brandTag}</span>
      </div>
    </footer>
  );
}
