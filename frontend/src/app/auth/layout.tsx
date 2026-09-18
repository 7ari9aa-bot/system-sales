import type { Metadata } from "next";
import { IBM_Plex_Sans_Arabic, Space_Grotesk, Archivo } from "next/font/google";
import Link from "next/link";
import "@/styles/fihrist.css";

const plexAr = IBM_Plex_Sans_Arabic({
  weight: ["300", "400", "500", "600", "700"],
  subsets: ["arabic", "latin"],
  variable: "--font-plex-ar",
  display: "swap",
});
const grotesk = Space_Grotesk({ weight: ["500", "600", "700"], subsets: ["latin"], variable: "--font-grotesk", display: "swap" });
const archivo = Archivo({ weight: ["500", "600"], subsets: ["latin"], variable: "--font-archivo", display: "swap" });
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
      <FihristRoot bare className={`${plexAr.variable} ${grotesk.variable} ${archivo.variable}`}>
        <div className="fh-auth">
          <header className="fh-auth-top">
            <Link href="/" className="fh-brand" aria-label="FIHRIST">
              <span className="fh-brand-mark" aria-hidden="true"><span>F</span></span>
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
