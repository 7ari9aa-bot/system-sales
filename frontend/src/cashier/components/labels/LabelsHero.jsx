import { Printer } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import PageHero from "@/cashier/components/ui-kit/PageHero";
import { BTN_PRIMARY } from "@/cashier/components/ui-kit/ledgerStyles";
import { fmtInt } from "@/cashier/lib/format";

// شريط عنوان شاشة الملصقات: صورة بكرة الملصقات مع زر المعاينة والطباعة.
export default function LabelsHero({ totalLabels, onPreview }) {
  return (
    <PageHero
      image="https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/8ef8f131c_generated_b34f58af.jpg"
      imageAlt="بكرة ملصقات على طابعة حرارية"
      title="طباعة الباركود"
      description="اسحب كميات فاتورة التوريد اللي دخلت المحل أو أدخل الأعداد يدويًا، ثم اطبع الملصقات بأسعارها"
    >
      <Button className={BTN_PRIMARY} disabled={!totalLabels} onClick={onPreview}>
        <Printer />
        {`معاينة وطباعة${totalLabels ? ` ${fmtInt(totalLabels)} ملصق` : ""}`}
      </Button>
    </PageHero>
  );
}