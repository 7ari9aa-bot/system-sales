"use client";

import Link from "next/link";
import { useI18n } from "@/components/public/i18n";

/** لوحة العلامة التجارية الجانبية في صفحات المصادقة — بثنائية اللغة. */
export function AuthAside() {
  const { t } = useI18n();
  return (
    <aside className="fh-auth-aside">
      <Link href="/" className="fh-brand" aria-label="FIHRIST">
        <span className="fh-brand-mark" aria-hidden="true"><span>F</span></span>
        <span className="fh-brand-name">FIHRIST</span>
      </Link>
      <h2>{t.auth.valueTitle}</h2>
      <p>{t.auth.valueSub}</p>
      <ul>
        {(t.auth.valuePoints as string[]).map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>
      <span className="fh-auth-badge">{t.auth.valueBadge}</span>
    </aside>
  );
}

export function AuthFoot() {
  const { t } = useI18n();
  return (
    <footer className="fh-auth-foot">
      <Link href="/">{t.brand}</Link>
      <span aria-hidden="true">·</span>
      <Link href="/privacy">{t.auth.privacy}</Link>
      <span aria-hidden="true">·</span>
      <Link href="/terms">{t.auth.terms}</Link>
    </footer>
  );
}
