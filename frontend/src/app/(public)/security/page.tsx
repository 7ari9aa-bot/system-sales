import type { Metadata } from "next";
import { PublicShell } from "@/components/public/shell";
import { SecurityBody } from "@/components/public/page-bodies";

export const metadata: Metadata = {
  title: "الأمان والتحكم — اللي مبني فعلًا — FIHRIST",
  description: "عزل بيانات لكل مستأجر على مستوى قاعدة البيانات، صلاحيات وأدوار، تدقيق كامل — بنكتب بس اللي شغّال.",
};

export default function SecurityPage() {
  return (
    <PublicShell>
      <SecurityBody />
    </PublicShell>
  );
}
