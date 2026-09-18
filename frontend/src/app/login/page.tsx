"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** تسجيل الدخول انتقل إلى /auth/login — التوجيه هنا يحمي الروابط القديمة. */
export default function LoginRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/auth/login");
  }, [router]);
  return (
    <main className="auth-wrap">
      <p className="muted">جارٍ التحويل…</p>
    </main>
  );
}
