import type { Metadata } from "next";
import { PublicShell } from "@/components/public/shell";
import { TermsBody } from "@/components/public/page-bodies";

export const metadata: Metadata = {
  title: "شروط الاستخدام — FIHRIST — FIHRIST",
  description: "شروط استخدام منصة FIHRIST — مكتوبة واضحة ومختصرة عشان تتقرأ فعلًا.",
};

export default function TermsPage() {
  return (
    <PublicShell>
      <TermsBody />
    </PublicShell>
  );
}
