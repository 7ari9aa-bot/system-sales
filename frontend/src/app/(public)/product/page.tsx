import type { Metadata } from "next";
import { PublicShell } from "@/components/public/shell";
import { ProductBody } from "@/components/public/page-bodies";

export const metadata: Metadata = {
  title: "المنتج — نظام تشغيل كامل لشغلك — FIHRIST",
  description: "محادثات موحدة، عملاء وطلبات، ذكاء اصطناعي مسيّس، أتمتة تشغيلية، تحليلات وبنية جاهزة للتوسع.",
};

export default function ProductPage() {
  return (
    <PublicShell>
      <ProductBody />
    </PublicShell>
  );
}
