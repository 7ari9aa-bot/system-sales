"use client";

/** /auth/signup — إنشاء حساب ضد الـAPI الحقيقي (register ثم login).
 *  التسجيل بسيط: الحقول المطلوبة من الـAPI فقط — كل باقي الإعداد يجي على مرحلة
 *  الإعداد بعد أول دخول (progressive onboarding). */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getTokens, setTokens } from "@/lib/api";
import { authPost } from "@/lib/auth-api";
import Link from "next/link";

type ErrState = { message: string; retryable: boolean } | null;

const PASSWORD_MIN = 8;

export default function AuthSignupPage() {
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [storeName, setStoreName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ErrState>(null);

  useEffect(() => {
    if (getTokens()) router.replace("/inbox");
  }, [router]);

  const pwValid = password.length >= PASSWORD_MIN;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    if (!pwValid) {
      setErr({ message: `كلمة المرور لازم تكون ${PASSWORD_MIN} حروف على الأقل.`, retryable: false });
      return;
    }
    setBusy(true);
    setErr(null);
    const tenantSlug =
      storeName.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40) ||
      `store-${Date.now()}`;

    const reg = await authPost("/auth/register", {
      email,
      password,
      full_name: fullName,
      tenant_name: storeName,
      tenant_slug: tenantSlug,
    }).catch(() => ({ ok: false as const, status: 0, message: undefined }));
    if (!reg.ok) {
      if (reg.status === 0) {
        setErr({ message: "مش قادرين نوصل للسيرفر. اتأكد من اتصالك وحاول تاني.", retryable: true });
      } else if (reg.status === 409) {
        setErr({ message: "البريد ده مستخدم بالفعل. سجّل الدخول أو استخدم بريد تاني.", retryable: false });
      } else if (reg.status === 429) {
        setErr({ message: "محاولات كثيرة جدًا. حاول مرة تانية بعد شوية.", retryable: true });
      } else if (reg.message) {
        setErr({ message: reg.message, retryable: true });
      } else {
        setErr({ message: "تعذر إنشاء الحساب. حاول مرة تانية.", retryable: true });
      }
      setBusy(false);
      return;
    }

    // التسجيل بيرجع البروفايل بدون توكنات — ندخل مباشرة
    const login = await authPost<{ access_token: string; refresh_token: string }>(
      "/auth/login",
      { email, password },
    ).catch(() => ({ ok: false as const, status: 0, message: undefined }));
    if (login.ok) {
      setTokens({ access_token: login.data.access_token, refresh_token: login.data.refresh_token });
      router.replace("/inbox");
      return;
    }
    setErr({
      message: "الحساب اتعمل لكن تعذر الدخول التلقائي — سجّل الدخول يدويًا.",
      retryable: false,
    });
    setBusy(false);
  }

  return (
    <div className="card auth-card" data-testid="auth-signup-card">
      <h1>أنشئ حسابك</h1>
      <p className="auth-sub">دقيقة واحدة وتكون جوه — باقي الإعداد بيتم بعد أول دخول.</p>

      <form className="auth-form" onSubmit={submit} noValidate>
        <div>
          <label htmlFor="storeName">اسم المتجر / النشاط</label>
          <input
            id="storeName"
            autoComplete="organization"
            value={storeName}
            onChange={(e) => setStoreName(e.target.value)}
            required
          />
        </div>
        <div>
          <label htmlFor="fullName">الاسم بالكامل</label>
          <input
            id="fullName"
            autoComplete="name"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            required
          />
        </div>
        <div>
          <label htmlFor="email">البريد الإلكتروني</label>
          <input
            id="email"
            type="email"
            dir="ltr"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>
        <div>
          <label htmlFor="password">كلمة المرور</label>
          <input
            id="password"
            type="password"
            dir="ltr"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            aria-describedby="pw-hint"
          />
          <small id="pw-hint" className={`pw-hint${pwValid ? " is-ok" : ""}`}>
            {pwValid ? "✓" : "•"} {PASSWORD_MIN} حروف على الأقل
          </small>
        </div>

        {err && (
          <div className="auth-error" role="alert">
            <p>{err.message}</p>
            {err.retryable && <button type="button" className="auth-error-retry" onClick={() => setErr(null)}>حاول مرة تانية</button>}
          </div>
        )}

        <button className="btn auth-submit" disabled={busy} data-testid="submit-signup">
          {busy ? "جارٍ إنشاء الحساب…" : "إنشاء الحساب"}
        </button>
      </form>

      <p className="auth-alt">
        عندك حساب بالفعل؟ <Link href="/auth/login">سجّل الدخول</Link>
      </p>
    </div>
  );
}
