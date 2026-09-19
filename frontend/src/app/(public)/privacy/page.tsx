import type { Metadata } from "next";
import { PrivacyBody } from "@/components/public/page-bodies";

export const metadata: Metadata = {
  title: "سياسة الخصوصية — FIHRIST — FIHRIST",
  description: "إيه اللي بنجمعه، وإزاي بنحميه، والذكاء الاصطناعي وبياناتك — بوضوح وبدون تعقيد.",
};

export default function PrivacyPage() {
  return (
      <PrivacyBody />
  );
}
