import type { Metadata } from "next";
import { IBM_Plex_Sans_Arabic, Space_Grotesk, Archivo } from "next/font/google";
import { Providers } from "./providers";
import "./globals.css";

/* Single font pipeline: self-hosted, non-blocking `next/font` at the root so
   every surface (public site, auth, dashboard) shares the same typefaces. */
const plexAr = IBM_Plex_Sans_Arabic({
  weight: ["300", "400", "600"],
  subsets: ["arabic", "latin"],
  variable: "--font-plex-ar",
  display: "swap",
});
const grotesk = Space_Grotesk({
  weight: ["600", "700"],
  subsets: ["latin"],
  variable: "--font-grotesk",
  display: "swap",
});
const archivo = Archivo({
  weight: ["500"],
  subsets: ["latin"],
  variable: "--font-archivo",
  display: "swap",
});

export const metadata: Metadata = {
  title: "سيلز أو إس — منصة البيع بالمحادثة",
  description: "إدارة الرسائل والطلبات والمخزون والذكاء الاصطناعي في مكان واحد",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="ar"
      dir="rtl"
      className={`${plexAr.variable} ${grotesk.variable} ${archivo.variable}`}
    >
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
