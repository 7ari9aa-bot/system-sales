import type { Metadata } from "next";
import { AiBody } from "@/components/public/page-bodies";

export const metadata: Metadata = {
  title: "الذكاء الاصطناعي — شغّال جوه قواعدك — FIHRIST",
  description: "مساعد بيفهم محادثاتك وينفذ إجراءات حقيقية عبر أدوات مصرح ليها فقط — بموافقات وحدود تكلفة وتدقيق كامل.",
};

export default function AIPage() {
  return (
      <AiBody />
  );
}
