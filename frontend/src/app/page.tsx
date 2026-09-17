"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { getTokens } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();
  useEffect(() => {
    router.replace(getTokens() ? "/inbox" : "/login");
  }, [router]);
  return (
    <main className="auth-wrap">
      <p className="muted">جارٍ التحميل…</p>
    </main>
  );
}
