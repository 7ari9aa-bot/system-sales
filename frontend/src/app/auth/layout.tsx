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
              <span className="fh-brand-mark" aria-hidden="true">F</span>
              <span className="fh-brand-name">FIHRIST</span>
            </Link>
          </header>

          <main className="fh-auth-main">{children}</main>

          <footer className="fh-auth-foot">
            <span>FIHRIST</span>
            <span aria-hidden="true">·</span>
            <span>فهرست</span>
          </footer>
        </div>
      </FihristRoot>
    </FihristProvider>
  );
}
