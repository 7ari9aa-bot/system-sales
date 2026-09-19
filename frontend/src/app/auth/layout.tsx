import type { Metadata } from "next";
import Link from "next/link";
import "@/styles/fihrist.css";
import { FihristProvider, FihristRoot } from "@/components/public/i18n";

export const metadata: Metadata = {
  title: "FIHRIST — تسجيل الدخول | Sign in",
  robots: { index: false },
};

/** Focused Authentication Shell — بدون موقع تسويقي، مع نفس هوية FIHRIST. */
export default function AuthLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <FihristProvider>
      <FihristRoot bare>
        <div className="fh-auth">
          <header className="fh-auth-top">
            <Link href="/" className="fh-brand" aria-label="FIHRIST">
              <span className="fh-brand-mark" aria-hidden="true"><span>F</span></span>
              <span className="fh-brand-name">FIHRIST</span>
            </Link>
            <span className="fh-auth-tagline">نظام تشغيل الأعمال بالمحادثة</span>
          </header>

          <main className="fh-auth-main">{children}</main>

          <footer className="fh-auth-foot">
            <Link href="/">العودة للصفحة الرئيسية</Link>
            <span aria-hidden="true">·</span>
            <Link href="/privacy">سياسة الخصوصية</Link>
            <span aria-hidden="true">·</span>
            <Link href="/terms">شروط الاستخدام</Link>
          </footer>
        </div>
      </FihristRoot>
    </FihristProvider>
  );
}
