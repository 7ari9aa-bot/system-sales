import type { Metadata } from "next";
import { PublicNavbar } from "@/components/public/navbar";
import { PublicFooter } from "@/components/public/footer";

export const metadata: Metadata = {
  title: "سيلز أو إس — نظام تشغيل واحد لشركتك",
  description:
    "العملاء، المحادثات، التجارة، الأتمتة، الذكاء الاصطناعي والتحليلات — كلها متصلة عبر سياق عمل واحد.",
};

export default function PublicLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="mk-shell">
      <PublicNavbar />
      {children}
      <PublicFooter />
    </div>
  );
}
