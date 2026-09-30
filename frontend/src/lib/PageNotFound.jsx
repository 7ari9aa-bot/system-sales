/** صفحة 404 — بدون أي استدعاء مصادقة؛ المسارات المحمية بيتوجهوا
 *  لصفحة الدخول من الراوتر نفسه. */

import { Link } from "react-router-dom";
import { useT } from "@/lib/i18n";

export default function PageNotFound() {
  const t = useT();
  return (
    <div className="fixed inset-0 grid place-items-center bg-background">
      <div className="text-center">
        <div className="font-display text-[64px] font-bold tracking-tight">404</div>
        <p className="text-[14px] text-muted-foreground mt-1">{t("notfound.title")}</p>
        <Link to="/" className="inline-flex mt-5 text-[13px] font-medium text-primary hover:underline">
          {t("notfound.back")}
        </Link>
      </div>
    </div>
  );
}
