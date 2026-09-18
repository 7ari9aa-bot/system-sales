import type { Metadata } from "next";
import { PublicShell } from "@/components/public/shell";
import { ConversationsBody } from "@/components/public/page-bodies";

export const metadata: Metadata = {
  title: "المحادثات — كل المحادثات في صندوق واحد — FIHRIST",
  description: "كل قنوات تواصل عملائك في مكان واحد — مع سياق كامل جنب كل محادثة ومسودات ذكاء اصطناعي وتحويل بالسياق الكامل.",
};

export default function ConversationsPage() {
  return (
    <PublicShell>
      <ConversationsBody />
    </PublicShell>
  );
}
