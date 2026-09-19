"use client";

/** /auth/signup — حقلان فقط (بريد + كلمة مرور) ضد الـAPI الحقيقي.
 *  الـbackend بيشقق اسم المساحة والـslug من البريد تلقائيًا — باقي التفاصيل
 *  بتظبط جوه النظام بعد أول دخول (progressive onboarding). */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getTokens, setTokens } from "@/lib/api";
import { authPost } from "@/lib/auth-api";
import { useI18n } from "@/components/public/i18n";
import Link from "next/link";

const PASSWORD_MIN = 8;

export default function AuthSignupPage() {
  const { t } = useI18n();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<{ message: string; retryable: boolean } | null>(null);

  useEffect(() => {
    if (getTokens()) router.replace("/inbox");
  }, [router]);

  const pwValid = password.length >= PASSWORD_MIN;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    if (!pwValid) {
      setErr({ message: t.auth.errPw, retryable: false });
      return;
    }
    setBusy(true);
    setErr(null);

    const reg = await authPost("/auth/register", { email, password }).catch(() => ({
      ok: false as const,
      status: 0,
      message: undefined,
    }));
    if (!reg.ok) {
      if (reg.status === 0) {
        setErr({ message: t.auth.errNetwork, retryable: true });
      } else if (reg.status === 409) {
        setErr({ message: t.auth.errExists, retryable: false });
      } else if (reg.status === 429) {
        setErr({ message: t.auth.errRate, retryable: true });
      } else if (reg.message) {
        setErr({ message: reg.message, retryable: true });
      } else {
        setErr({ message: t.auth.errCreate, retryable: true });
      }
      setBusy(false);
      return;
    }

    const login = await authPost<{ access_token: string; refresh_token: string }>(
      "/auth/login",
      { email, password },
    ).catch(() => ({ ok: false as const, status: 0, message: undefined }));
    if (login.ok) {
      setTokens({ access_token: login.data.access_token, refresh_token: login.data.refresh_token });
      router.replace("/inbox");
      return;
    }
    setErr({ message: t.auth.errAutoLogin, retryable: false });
    setBusy(false);
  }

  return (
    <div className="fh-card fh-auth-card" data-testid="auth-signup-card">
      <h1>{t.auth.signupTitle}</h1>
      <p className="fh-auth-sub">{t.auth.signupSub}</p>

      <form className="fh-auth-form" onSubmit={submit} noValidate>
        <div>
          <label htmlFor="email">{t.auth.email}</label>
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
          <label htmlFor="password">{t.auth.password}</label>
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
          <small id="pw-hint" className={`fh-pw-hint${pwValid ? " is-ok" : ""}`}>
            {pwValid ? "✓" : "•"} {t.auth.pwHint}
          </small>
        </div>

        {err && (
          <div className="fh-auth-error" role="alert">
            <p>{err.message}</p>
            <button type="button" onClick={() => setErr(null)}>{t.auth.dismiss}</button>
          </div>
        )}

        <button className="fh-btn fh-auth-submit" disabled={busy} data-testid="submit-signup">
          {busy ? t.auth.submittingSignup : t.auth.submitSignup}
        </button>
        <p className="fh-auth-trust">مجاني خلال الوصول المبكر · بدون بطاقة · بياناتك معزولة من أول يوم</p>
      </form>

      <p className="fh-auth-alt">
        {t.auth.haveAccount}{" "}
        <Link href="/auth/login">{t.auth.signin}</Link>
      </p>
    </div>
  );
}
