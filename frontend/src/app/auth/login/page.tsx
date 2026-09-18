"use client";

/** /auth/login — شغّال ضد الـAPI الحقيقي (/api/v1/auth/login).
 *  الحالات: افتراضي · تحميل · بيانات غير صحيحة · تجاوز المحاولات · خطأ شبكة.
 *  مفيش Google/SSO — مش موجودين في الـbackend فعلًا. */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { API_BASE_URL, API_PREFIX, getTokens, setTokens } from "@/lib/api";
import Link from "next/link";

type ErrState = { message: string; retryable: boolean } | null;

function mapError(status: number, apiMessage?: string): ErrState {
  if (status === 401 || status === 403 || status === 400) {
    return { message: "البريد الإلكتروني أو كلمة المرور غير صحيحة.", retryable: false };
  }
  if (status === 429) {
    return { message: "محاولات كثيرة جدًا. حاول مرة تانية بعد شوية.", retryable: true };
  }
  if (apiMessage) return { message: apiMessage, retryable: true };
  return { message: "حدث خطأ غير متوقع. حاول مرة تانية.", retryable: true };
}

export default function AuthLoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ErrState>(null);

  useEffect(() => {
    if (getTokens()) router.replace("/inbox");
  }, [router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return; // لا إعادة إرسال أثناء التحميل
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(`${API_BASE_URL}${API_PREFIX}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw Object.assign(new Error(), { status: res.status, apiMessage: data?.error?.message ?? data?.detail });
      }
      const pair = await res.json();
      setTokens({ access_token: pair.access_token, refresh_token: pair.refresh_token });
      router.replace("/inbox");
    } catch (e) {
      if (e instanceof TypeError) {
        setErr({ message: "مش قادرين نوصل للسيرفر. اتأكد من اتصالك وحاول تاني.", retryable: true });
      } else {
        const ex = e as Error & { status?: number; apiMessage?: string };
        setErr(mapError(ex.status ?? 0, ex.apiMessage));
      }
      setBusy(false);
    }
  }

  return (
    <div className="card auth-card" data-testid="auth-login-card">
      <h1>أهلًا بعودتك</h1>
      <p className="auth-sub">سجّل الدخول للمتابعة إلى مساحة عملك.</p>

      <form className="auth-form" onSubmit={submit} noValidate>
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
            aria-describedby={err ? "auth-error" : undefined}
          />
        </div>
        <div>
          <label htmlFor="password">كلمة المرور</label>
          <input
            id="password"
            type="password"
            dir="ltr"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>

        {err && (
          <div className="auth-error" id="auth-error" role="alert">
            <p>{err.message}</p>
            {err.retryable && <button type="button" className="auth-error-retry" onClick={() => setErr(null)}>حاول مرة تانية</button>}
          </div>
        )}

        <button className="btn auth-submit" disabled={busy} data-testid="submit-login">
          {busy ? "جارٍ تسجيل الدخول…" : "تسجيل الدخول"}
        </button>
      </form>

      <p className="auth-alt">
        معندكش حساب؟ <Link href="/auth/signup">أنشئ حساب</Link>
      </p>
    </div>
  );
}
