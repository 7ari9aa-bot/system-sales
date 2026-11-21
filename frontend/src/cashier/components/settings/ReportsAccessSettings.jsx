import ShopPolicySettings from "./ShopPolicySettings";

// من يرى تقارير التكلفة والربح: الربح والتصريف والمخزون الراكد وتخفيض الموسم. صاحب المحل
// يراها دائمًا، والكاشير لا يراها أبدًا، والمدير يراها ما دام هذا الإعداد مفعّلًا. الخادم هو الذي
// يقرر؛ هذه الشاشة تعرض الإعداد وتحفظه فقط.
export const REPORTS_ACCESS_KEYS = ["reports.managers_see_profit"];

export default function ReportsAccessSettings() {
  return (
    <ShopPolicySettings
      domain="business"
      keys={REPORTS_ACCESS_KEYS}
      title="من يرى التكلفة والربح"
      description="تقارير الربح والتصريف والمخزون الراكد وتخفيض الموسم. أنت ترى كل هذا دائمًا، والكاشير لا يراه أبدًا."
      emptyText="لا توجد إعدادات قابلة للتعديل."
    />
  );
}
