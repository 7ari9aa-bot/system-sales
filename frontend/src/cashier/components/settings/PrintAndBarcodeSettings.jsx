import ShopPolicySettings from "./ShopPolicySettings";

// الفاتورة المطبوعة: مقاس الورق وعدد النسخ والشعار وسطر أعلى وأسفل الإيصال وتفصيل الضريبة. الإيصال والمعاينة
// يقرآنها من الخادم وقت الطباعة. بادئة الفاتورة وصيغة الباركود لا يقرأهما شيء بعد، فلا تظهر هنا.
export const PRINT_KEYS = [
  "print.paper_width",
  "print.copies",
  "print.show_logo",
  "print.header_text",
  "print.footer_text",
  "print.show_tax_detail",
];

export default function PrintAndBarcodeSettings() {
  return (
    <ShopPolicySettings
      domain="print"
      keys={PRINT_KEYS}
      title="الفاتورة المطبوعة"
      description="شكل الإيصال المطبوع. التعديل يسري على أول إيصال بعد الحفظ."
      emptyText="لا توجد إعدادات قابلة للتعديل."
    />
  );
}
