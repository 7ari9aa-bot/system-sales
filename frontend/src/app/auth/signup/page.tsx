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
import { Eye, EyeOff, Mail, Lock, Loader2 } from "lucide-react";

const PASSWORD_MIN = 8;

export default function AuthSignupPage() {
  const { t } = useI18n();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<{
    message: string;
    retryable: boolean;
    showLogin?: boolean;
  } | null>(null);
  const [showPw, setShowPw] = useState(false);

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

    // جسر توافقي: نشقق اسم المساحة والـslug من البريد محليًا — يشتغل مع
    // عقد الباك القديم (الحقول مطلوبة) والجديد (بيحترم القيم المرسلة) سوا.
    const localPart = email.split("@", 1)[0];
    const segments = localPart.split(/[._-]+/).filter(Boolean);
    if (segments.length > 1 && /^(?:\d+|[0-9a-f]{6,})$/.test(segments[segments.length - 1])) {
      segments.pop();
    }
    const displayName = segments.join(" ").trim().toUpperCase() || localPart;
    const tenantSlug =
      localPart.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40) ||
      `workspace-${Date.now()}`;

    const reg = await authPost("/auth/register", {
      email,
      password,
      tenant_name: displayName,
      tenant_slug: tenantSlug,
      full_name: displayName,
    }).catch(() => ({
      ok: false as const,
      status: 0,
      message: undefined,
    }));

    if (!reg.ok) {
      if (reg.status === 0) {
        setErr({ message: t.auth.errNetwork, retryable: true });
      } else if (reg.status === 409) {
        /* البريد مسجل — نحاول ندخّل تلقائيًا بنفس كلمة المرور */
        const auto = await authPost<{ access_token: string; refresh_token: string }>(
          "/auth/login",
          { email, password },
        ).catch(() => ({ ok: false as const, status: 0, message: undefined }));
        if (auto.ok) {
          setTokens({
            access_token: auto.data.access_token,
            refresh_token: auto.data.refresh_token,
          });
          router.replace("/inbox");
          return;
        }
        /* كلمة المرور مش مطابقة — نوجّه المستخدم لصفحة الدخول */
        setErr({
          message: t.auth.errExistsLogin,
          retryable: false,
          showLogin: true,
        });
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

    // التسجيل نجح — ندخّل تلقائيًا
    const login = await authPost<{ access_token: string; refresh_token: string }>(
      "/auth/login",
      { email, password },
    ).catch(() => ({ ok: false as const, status: 0, message: undefined }));
    if (login.ok) {
      setTokens({
        access_token: login.data.access_token,
        refresh_token: login.data.refresh_token,
      });
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
        <div className="fh-input-group">
          <label htmlFor="email">{t.auth.email}</label>
          <div className="fh-input-wrap">
            <Mail className="fh-input-icon" size={18} strokeWidth={1.5} />
            <input
              id="email"
              type="email"
              dir="ltr"
              autoComplete="email"
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
        </div>

        <div className="fh-input-group">
          <label htmlFor="password">{t.auth.password}</label>
          <div className="fh-input-wrap fh-pw-field">
            <Lock className="fh-input-icon" size={18} strokeWidth={1.5} />
            <input
              id="password"
              type={showPw ? "text" : "password"}
              dir="ltr"
              autoComplete="new-password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              aria-describedby="pw-hint"
            />
            <button
              type="button"
              className="fh-pw-toggle"
              onClick={() => setShowPw((s) => !s)}
              aria-label={showPw ? t.auth.hidePw : t.auth.showPw}
            >
              {showPw
                ? <EyeOff size={18} strokeWidth={1.5} />
                : <Eye size={18} strokeWidth={1.5} />}
            </button>
          </div>
          <small id="pw-hint" className={`fh-pw-hint${pwValid ? " is-ok" : ""}`}>
            {pwValid ? "✓" : "•"} {t.auth.pwHint}
          </small>
        </div>

        {err && (
          <div className="fh-auth-error" role="alert">
            <p>{err.message}</p>
            <span className="fh-auth-error-actions">
              {err.showLogin && (
                <Link href="/auth/login" className="fh-auth-error-link">
                  {t.auth.signin} →
                </Link>
              )}
              <button type="button" onClick={() => setErr(null)}>
                {t.auth.dismiss}
              </button>
            </span>
          </div>
        )}

        <button
          className="fh-btn fh-auth-submit"
          disabled={busy}
          data-testid="submit-signup"
        >
          {busy ? (
            <>
              <Loader2 size={18} className="fh-spin" />
              {t.auth.submittingSignup}
            </>
          ) : (
            t.auth.submitSignup
          )}
        </button>
        <p className="fh-auth-trust">
          مجاني خلال الوصول المبكر · بدون بطاقة · بياناتك معزولة من أول يوم
        </p>
      </form>

      <p className="fh-auth-alt">
        لسه بتفكر؟{" "}
        <Link href="/#try">جرّب المساعد التجريبي الأول</Link>
      </p>
      <p className="fh-auth-alt">
        {t.auth.haveAccount}{" "}
        <Link href="/auth/login">{t.auth.signin}</Link>
      </p>
    </div>
  );
}
