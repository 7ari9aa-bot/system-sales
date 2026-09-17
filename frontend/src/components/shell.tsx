"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, getTokens, setTokens } from "@/lib/api";
import { t } from "@/lib/t";

const NAV = [
  { href: "/inbox", label: t.inbox },
  { href: "/products", label: t.products },
  { href: "/inventory", label: t.inventory },
  { href: "/orders", label: t.orders },
  { href: "/customers", label: t.customers },
  { href: "/ai", label: t.ai },
  { href: "/settings", label: t.settings },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [email, setEmail] = useState<string>("");

  useEffect(() => {
    if (!getTokens()) {
      router.replace("/login");
      return;
    }
    api<{ email: string }>("/auth/me")
      .then((me) => setEmail(me.email))
      .catch(() => {});
  }, [router]);

  function logout() {
    setTokens(null);
    router.replace("/login");
  }

  return (
    <div className="shell">
      <nav className="sidebar">
        <div className="brand">{t.brand}</div>
        {NAV.map((item) => (
          <Link key={item.href} href={item.href} className={pathname.startsWith(item.href) ? "active" : ""}>
            {item.label}
          </Link>
        ))}
        <div style={{ flex: 1 }} />
        {email && (
          <div style={{ padding: "0 0.85rem" }}>
            <div className="muted" dir="ltr" style={{ fontSize: 12, wordBreak: "break-all" }}>
              {email}
            </div>
            <button className="btn btn-secondary" style={{ width: "100%", marginTop: "0.5rem" }} onClick={logout}>
              {t.logout}
            </button>
          </div>
        )}
      </nav>
      <main className="main">{children}</main>
    </div>
  );
}
