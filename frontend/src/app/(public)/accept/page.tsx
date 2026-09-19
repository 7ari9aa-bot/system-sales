"use client";

/** /accept?token=... — قبول دعوة عضوية. صفحة عامة (بدون توكن دخول). */

import { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useI18n } from "@/components/public/i18n";
import { useAcceptInvitation } from "@/lib/queries";

function AcceptForm() {
  const { t } = useI18n();
  const params = useSearchParams();
  const token = params.get("token") ?? "";

  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const accept = useAcceptInvitation();

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy || done) return;
    setErr(null);
    if (password.length < 8) {
      setErr(t.auth.errPw);
      return;
    }
    if (password !== confirm) {
      setErr("كلمة المرور وتأكيدها مش متطابقين.");
      return;
    }
    setBusy(true);
    accept.mutate(
      { token, password, full_name: fullName.trim() },
      {
        onSuccess: () => setDone(true),
        onError: (e) => setErr(e.message),
        onSettled: () => setBusy(false),
      },
    );
  }

  if (!token) {
    return (
      <div className="fh-card fh-auth-card" data-testid="accept-missing-token">
        <h1>قبول الدعوة</h1>
        <p className="fh-auth-sub">الرابط غير صحيح — تأكد إنك فاتح الرابط اللي وصلك بالبريد كامل.</p>
        <Link href="/" className="fh-btn fh-btn-secondary">العودة للرئيسية</Link>
      </div>
    );
  }

  if (done) {
    return (
      <div className="fh-card fh-auth-card" data-testid="accept-success">
        <h1>تم قبول الدعوة</h1>
        <p className="fh-auth-sub">تم قبول الدعوة، سجل دخولك الآن لتبدأ العمل.</p>
        <Link href="/auth/login" className="fh-btn fh-auth-submit" data-testid="accept-go-login">
          تسجيل الدخول
        </Link>
      </div>
    );
  }

  return (
    <div className="fh-card fh-auth-card" data-testid="accept-form">
      <h1>قبول الدعوة</h1>
      <p className="fh-auth-sub">خلّص بياناتك عشان تنضم لمساحة العمل.</p>

      <form className="fh-auth-form" onSubmit={submit} noValidate>
        <div>
          <label htmlFor="accept-name">{t.auth.fullName}</label>
          <input
            id="accept-name"
            type="text"
            autoComplete="name"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            required
          />
        </div>
        <div>
          <label htmlFor="accept-password">{t.auth.password}</label>
          <input
            id="accept-password"
            type="password"
            dir="ltr"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
          />
          <small style={{ color: "var(--muted)", fontSize: "12.5px" }}>{t.auth.pwHint}</small>
        </div>
        <div>
          <label htmlFor="accept-confirm">تأكيد كلمة المرور</label>
          <input
            id="accept-confirm"
            type="password"
            dir="ltr"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
            minLength={8}
          />
        </div>

        {err && (
          <div className="fh-auth-error" role="alert">
            <p>{err}</p>
            <button type="button" onClick={() => setErr(null)}>{t.auth.dismiss}</button>
          </div>
        )}

        <button className="fh-btn fh-auth-submit" disabled={busy} data-testid="submit-accept">
          {busy ? "جارٍ القبول…" : "قبول الدعوة"}
        </button>
      </form>
    </div>
  );
}

export default function AcceptPage() {
  return (
    <section className="fh-section">
      <div className="fh-container">
        <Suspense fallback={null}>
          <AcceptForm />
        </Suspense>
      </div>
    </section>
  );
}
