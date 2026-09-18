"use client";

/** /auth/login — شغّال ضد الـAPI الحقيقي، ثنائي اللغة، فاتح/داكن.
 *  مفيش Google/SSO — مش موجودين في الـbackend فعلًا. */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getTokens, setTokens } from "@/lib/api";
import { authPost } from "@/lib/auth-api";
import { useI18n } from "@/components/public/i18n";
import Link from "next/link";

export default function AuthLoginPage() {
  const { t } = useI18n();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<{ message: string; retryable: boolean } | null>(null);

  useEffect(() => {
    if (getTokens()) router.replace("/inbox");
  }, [router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setErr(null);
    const res = await authPost<{ access_token: string; refresh_token: string }>(
      "/auth/login",
      { email, password },
    ).catch(() => ({ ok: false as const, status: 0, message: undefined }));
    if (res.ok) {
      setTokens({ access_token: res.data.access_token, refresh_token: res.data.refresh_token });
      router.replace("/inbox");
      return;
    }
    if (res.status === 0) {
      setErr({ message: t.auth.errNetwork, retryable: true });
    } else if (res.status === 401 || res.status === 403 || res.status === 400) {
      setErr({ message: t.auth.errInvalid, retryable: false });
    } else if (res.status === 429) {
      setErr({ message: t.auth.errRate, retryable: true });
    } else if (res.message) {
      setErr({ message: res.message, retryable: true });
    } else {
      setErr({ message: t.auth.errGeneric, retryable: true });
    }
    setBusy(false);
  }

  return (
    <div className="fh-card fh-auth-card" data-testid="auth-login-card">
      <h1>{t.auth.loginTitle}</h1>
      <p className="fh-auth-sub">{t.auth.loginSub}</p>

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
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>

        {err && (
          <div className="fh-auth-error" role="alert">
            <p>{err.message}</p>
            <button type="button" onClick={() => setErr(null)}>{t.auth.dismiss}</button>
          </div>
        )}

        <button className="fh-btn fh-auth-submit" disabled={busy} data-testid="submit-login">
          {busy ? t.auth.submittingLogin : t.auth.submitLogin}
        </button>
      </form>

      <p className="fh-auth-alt">
        {t.auth.noAccount} <Link href="/auth/signup">{t.auth.createAccount}</Link>
      </p>
    </div>
  );
}
