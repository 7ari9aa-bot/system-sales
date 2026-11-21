import ShopPolicySettings from "./ShopPolicySettings";
import ReopenActivitySetup from "@/cashier/components/setup/ReopenActivitySetup";

// بيانات المحل: الاسم والعنوان والهاتف والرقم الضريبي. تُرسم من تعريفات محرك الإعدادات نفسه، والإيصال المطبوع
// وإيصال الضرائب يقرآنها من نفس المكان، فما يُكتب هنا يظهر على الإيصال فعلًا. نستبعد اختيار النشاط (business.vertical)
// لأنه يغيّر القدرات المفعّلة ولا يُغيَّر من شاشة بيانات.
export const SHOP_PROFILE_KEYS = [
  "business.trade_name",
  "business.legal_name",
  "business.address.line1",
  "business.address.city",
  "business.phone",
  "business.tax_id",
];

export default function ShopProfileForm() {
  return (
    <>
      <ShopPolicySettings
        domain="business"
        keys={SHOP_PROFILE_KEYS}
        title="بيانات المحل"
        description="الاسم والعنوان والهاتف والرقم الضريبي. تظهر على الإيصال المطبوع."
        emptyText="لا توجد بيانات قابلة للتعديل."
      />
      <ReopenActivitySetup />
    </>
  );
}
