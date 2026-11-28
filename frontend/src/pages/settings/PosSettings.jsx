import React from "react";
import { useNavigate, useParams } from "react-router-dom";
import { DatabaseBackup, FileCheck2, ScrollText, Printer, Store, Tags, Users, MonitorSmartphone, Undo2 } from "lucide-react";
import { Toaster } from "@/applications/apparel/components/ui/sonner";
import { useI18n, useT } from "@/lib/i18n";
import "@/applications/apparel/cashier.css";
import ShopProfileForm from "@/applications/apparel/components/settings/ShopProfileForm";
import PrintAndBarcodeSettings from "@/applications/apparel/components/settings/PrintAndBarcodeSettings";
import ReportsAccessSettings from "@/applications/apparel/components/settings/ReportsAccessSettings";
import CategoriesSettings from "@/applications/apparel/components/settings/CategoriesSettings";
import UsersSettings from "@/applications/apparel/components/settings/UsersSettings";
import BackupTab from "@/applications/apparel/components/settings/BackupTab";
import ShopPolicySettings from "@/applications/apparel/components/settings/ShopPolicySettings";
import ReceiptTracking from "@/applications/apparel/components/settings/ReceiptTracking";
import TaxSettings from "@/applications/apparel/components/settings/TaxSettings";
import DevicesSection from "./pos/DevicesSection";

/** إعدادات نقاط البيع — كل قسم بمساره بدل تسعة أقسام مكدّسة في صفحة واحدة.
 *
 * الصفحة دي غلاف بس: بتقرا القسم من المسار (/settings/pos/<section>) وبترسمه لوحده،
 * فالفواتير أو الأجهزة بتفتح في تبويب مستقل بحالتها وبعنوانها، والرجوع بيحافظ على القسم.
 * أجهزة الكاشير والبروفايلات (٥٤١ سطر) اتنقلت لملفها src/pages/settings/pos/DevicesSection.jsx
 * بدون حذف أي سطر. أي رابط قديم على /settings/pos بيفتح «بيانات المحل».
 */

// ترتيب الأقسام هو ترتيب شريط التبويبات، وكل واحد ليه slug ثابت في المسار.
const SECTIONS = [
  { value: "shop", labelKey: "settings.pos.shop", icon: Store, render: () => <ShopProfileForm /> },
  { value: "policy", labelKey: "settings.pos.policy", icon: Undo2, render: () => <ShopPolicySettings /> },
  { value: "einvoice", labelKey: "settings.pos.einvoice", icon: FileCheck2, render: () => <TaxSettings /> },
  { value: "receipts", labelKey: "settings.pos.receipts", icon: ScrollText, render: () => <ReceiptTracking /> },
  { value: "print", labelKey: "settings.pos.print", icon: Printer, render: () => <PrintAndBarcodeSettings /> },
  { value: "lists", labelKey: "settings.pos.lists", icon: Tags, render: () => <CategoriesSettings /> },
  {
    value: "users",
    labelKey: "settings.pos.users",
    icon: Users,
    render: () => (
      <>
        <UsersSettings />
        <ReportsAccessSettings />
      </>
    ),
  },
  { value: "backup", labelKey: "settings.pos.backup", icon: DatabaseBackup, render: () => <BackupTab /> },
  { value: "devices", labelKey: "settings.pos.devices", icon: MonitorSmartphone, render: () => <DevicesSection /> },
];

export const POS_SECTION_SLUGS = SECTIONS.map((s) => s.value);

/** القسم المطلوب، أو الأول لو المسار بلا قسم أو بقسم غير معروف. */
export function resolvePosSection(slug) {
  return SECTIONS.find((s) => s.value === slug) ?? SECTIONS[0];
}

export default function PosSettings() {
  const { section } = useParams();
  const navigate = useNavigate();
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const active = resolvePosSection(section);

  return (
    <div className="cashier-root" dir={isAr ? "rtl" : "ltr"}>
      <nav
        aria-label={t("settings.pos.sectionLabel")}
        className="flex h-auto w-full flex-wrap justify-start gap-1 rounded-none border-b border-border bg-transparent p-0"
      >
        {SECTIONS.map((item) => {
          const Icon = item.icon;
          const isActive = item.value === active.value;
          return (
            <button
              key={item.value}
              type="button"
              role="tab"
              aria-selected={isActive}
              aria-current={isActive ? "page" : undefined}
              onClick={() => navigate(`/settings/pos/${item.value}`)}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-[12.5px] font-medium transition-colors ${
                isActive ? "bg-[#E8761A] text-white" : "text-muted-foreground hover:bg-muted"
              }`}
            >
              <Icon className="h-4 w-4" />
              {t(item.labelKey)}
            </button>
          );
        })}
      </nav>
      <div className="mt-4" data-section={active.value}>
        {active.render()}
      </div>
      <Toaster position="top-center" dir={isAr ? "rtl" : "ltr"} />
    </div>
  );
}
