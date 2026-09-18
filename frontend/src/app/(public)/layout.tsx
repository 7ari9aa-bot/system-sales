import type { Metadata, Viewport } from "next";
import "@/styles/fihrist.css";
import { FihristProvider, FihristRoot } from "@/components/public/i18n";
import { PublicNavbar } from "@/components/public/navbar";
import { PublicFooter } from "@/components/public/footer";

export const metadata: Metadata = {
  title: "FIHRIST — One connected system for your business | فهرست",
  description:
    "Customers, conversations, commerce, automation, AI and analytics — connected through one business context. العملاء والمحادثات والتجارة والأتمتة والذكاء الاصطناعي في سياق عمل واحد.",
  alternates: { canonical: "/" },
  openGraph: {
    title: "FIHRIST — One business context. One operating system.",
    description:
      "Conversations, customers, orders, automation and AI — connected in one system.",
    type: "website",
  },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f7fb" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0d16" },
  ],
};

export default function PublicLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <FihristProvider>
      <FihristRoot>
        <PublicNavbar />
        {children}
        <PublicFooter />
      </FihristRoot>
    </FihristProvider>
  );
}
