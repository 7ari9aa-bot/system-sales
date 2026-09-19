import type { Metadata } from "next";
import { ContextBody } from "@/components/public/page-bodies";

export const metadata: Metadata = {
  title: "سياق العمل — كل حاجة متصلة بحاجة — FIHRIST",
  description: "المحادثة مربوطة بالعميل، والعميل بطلبه، والطلب بدفعته — مصدر حقيقة واحد بدل أدوات مفككة.",
};

export default function ContextPage() {
  return (
      <ContextBody />
  );
}
