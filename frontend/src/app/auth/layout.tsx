import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "تسجيل الدخول — سيلز أو إس",
  robots: { index: false },
};

/** Focused Authentication Shell — بدون موقع تسويقي، التركيز على النموذج. */
export default function AuthLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="auth-page">
      <header className="auth-top">
        <Link href="/" className="mk-brand" aria-label="سيلز أو إس — الصفحة الرئيسية">
          <span className="mk-brand-mark" aria-hidden="true">س</span>
          <span className="mk-brand-name">سيلز أو إس</span>
        </Link>
      </header>

      <main className="auth-main">{children}</main>

      <footer className="auth-foot">
        <span>الخصوصية</span>
        <span aria-hidden="true">·</span>
        <span>الشروط</span>
      </footer>
    </div>
  );
}
