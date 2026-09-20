"use client";

import { useI18n } from "@/components/public/i18n";

/** شريط إشارات الثقة — تحت الهيرو مباشرة */
export function TrustStrip() {
  const { t } = useI18n();
  const items = t.trustSignals as string[];
  if (!items || items.length === 0) return null;
  return (
    <div className="fh-trust-strip" aria-label="trust signals">
      {items.map((s) => (
        <span key={s} className="fh-trust-item">
          <span className="fh-trust-check" aria-hidden="true">✓</span>
          {s}
        </span>
      ))}
    </div>
  );
}
