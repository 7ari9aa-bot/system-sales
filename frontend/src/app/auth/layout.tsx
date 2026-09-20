import type { Metadata } from "next";
import Link from "next/link";
import "@/styles/fihrist.css";
import { FihristProvider, FihristRoot } from "@/components/public/i18n";
import { AuthAside, AuthFoot } from "@/components/public/auth-aside";

export const metadata: Metadata = {
  title: "FIHRIST — تسجيل الدخول | Sign in",
  robots: { index: false },
};

/** Authentication Shell — split-screen بلوحة علامة تجارية وقائمة تركيز على الجنب. */
export default function AuthLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <FihristProvider>
      <FihristRoot bare>
        <div className="fh-auth">
          <div className="fh-auth-shell">
            <AuthAside />
            <div className="fh-auth-main">
              <header className="fh-auth-top">
                <Link href="/" className="fh-brand" aria-label="FIHRIST">
                  <span className="fh-brand-mark" aria-hidden="true"><span>F</span></span>
                  <span className="fh-brand-name">FIHRIST</span>
                </Link>
              </header>
              <div className="fh-auth-card-wrap">{children}</div>
              <AuthFoot />
            </div>
          </div>
        </div>
      </FihristRoot>
    </FihristProvider>
  );
}
