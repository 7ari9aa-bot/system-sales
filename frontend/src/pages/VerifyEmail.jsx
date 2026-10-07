import React, { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2, MailCheck, MailWarning } from "lucide-react";
import AuthLayout from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { publicApi } from "@/lib/api";
import { useI18n } from "@/lib/marketing-i18n";

const c = (ar, en) => ({ ar, en });
const tx = (copy, locale) => copy[locale];

/**
 * Landing page for the confirmation links POSTed by the identity email
 * worker ({frontend_public_url}/verify-email#token=...). Mirrors
 * ResetPassword.jsx: the token travels in the URL fragment so it never
 * reaches server access logs, and is stripped from browser history the
 * moment the page reads it. Confirmation auto-runs — the visitor got here
 * by clicking a one-time link, there is nothing to type.
 */
export default function VerifyEmail() {
  const { locale } = useI18n();
  const [state, setState] = useState("verifying"); // verifying | complete | missing | invalid | error
  const [email, setEmail] = useState("");
  const [resendSent, setResendSent] = useState(false);
  const [resending, setResending] = useState(false);
  const [resendError, setResendError] = useState("");
  const submitted = useRef(false);

  useEffect(() => {
    if (submitted.current) return;
    submitted.current = true;
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    const token = fragment.get("token") || "";
    if (window.location.hash) {
      window.history.replaceState(
        window.history.state,
        "",
        `${window.location.pathname}${window.location.search}`,
      );
    }
    if (!token) {
      setState("missing");
      return;
    }
    publicApi("/auth/verify-email", { body: { token } })
      .then(() => setState("complete"))
      .catch((err) => {
        const bad = err?.code === "validation_error" || err?.status === 400 || err?.status === 404;
        setState(bad ? "invalid" : "error");
      });
  }, []);

  const handleResend = async (event) => {
    event.preventDefault();
    setResendError("");
    setResending(true);
    try {
      // Deliberately neutral (202 always): the backend answers identically
      // for known, unknown, verified and throttled addresses.
      await publicApi("/auth/resend-verification", { body: { email: email.trim() } });
      setResendSent(true);
    } catch {
      setResendError(tx(
        c("تعذّر الإرسال الآن. حاول بعد قليل.", "Couldn't send right now. Try again shortly."),
        locale,
      ));
    } finally {
      setResending(false);
    }
  };

  const resendForm = (
    <form onSubmit={handleResend} className="space-y-4 mt-4">
      <div className="space-y-2">
        <Label htmlFor="verify-email" dir="auto">{tx(c("البريد الإلكتروني", "Email address"), locale)}</Label>
        <Input
          id="verify-email"
          type="email"
          name="verify-email"
          autoComplete="email"
          required
          maxLength={254}
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className="auth-input"
        />
      </div>
      {resendError && <div className="auth-error" role="alert" dir="auto">{resendError}</div>}
      <Button type="submit" className="auth-btn-primary w-full" disabled={resending}>
        {resending ? (
          <><Loader2 className="mr-2 h-4 w-4 animate-spin" />{tx(c("جارٍ الإرسال...", "Sending..."), locale)}</>
        ) : tx(c("أعد إرسال رابط التأكيد", "Resend confirmation link"), locale)}
      </Button>
    </form>
  );

  return (
    <AuthLayout
      icon={state === "complete" ? MailCheck : MailWarning}
      title={tx(c("تأكيد البريد الإلكتروني", "Confirm your email"), locale)}
      subtitle={tx(
        c("نأكد بريدك لحماية حسابك وتمكين الدعوات.", "We verify your email to protect your account and enable invitations."),
        locale,
      )}
    >
      {state === "verifying" && (
        <div className="auth-note flex items-center gap-2" role="status" aria-live="polite" dir="auto">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden="true" />
          <span className="text-[13.5px]">{tx(c("جارٍ التحقق من الرابط...", "Verifying your link..."), locale)}</span>
        </div>
      )}
      {state === "complete" && (
        <div className="auth-note" role="status" aria-live="polite">
          <p className="text-[13.5px] leading-[1.8]">
            {tx(c("تم تأكيد بريدك. الحساب جاهز لقبول الدعوات.", "Your email is confirmed. The account can now accept invitations."), locale)}
          </p>
          <Link to="/login" className="auth-link inline-flex mt-3">
            {tx(c("الانتقال لتسجيل الدخول", "Continue to sign in"), locale)}
          </Link>
        </div>
      )}
      {(state === "invalid" || state === "error") && (
        <div className="auth-note" role="alert">
          <p className="text-[13.5px] leading-[1.8]">
            {state === "invalid"
              ? tx(c("الرابط غير صالح أو انتهت صلاحيته أو تم استخدامه.", "This link is invalid, expired, or already used."), locale)
              : tx(c("تعذّر التحقق الآن. حاول مرة أخرى.", "We couldn't verify right now. Please try again."), locale)}
          </p>
        </div>
      )}
      {state === "missing" && (
        <div className="auth-note">
          <p className="text-[13.5px] leading-[1.8]">
            {tx(c("رابط التأكيد غير موجود. أدخل بريدك وسنرسل رابطًا جديدًا.", "The confirmation link is missing. Enter your email and we'll send a new one."), locale)}
          </p>
        </div>
      )}
      {state !== "verifying" && state !== "complete" && (
        resendSent ? (
          <div className="auth-note" role="status" aria-live="polite">
            <p className="text-[13.5px] leading-[1.8]">
              {tx(c("لو البريد مرتبط بحساب، ستصلك رسالة تأكيد قريبًا.", "If that email belongs to an account, a confirmation message is on its way."), locale)}
            </p>
          </div>
        ) : resendForm
      )}
      {state !== "verifying" && state !== "complete" && (
        <Link to="/login" className="auth-link inline-flex mt-4">
          {tx(c("رجوع لتسجيل الدخول", "Back to sign in"), locale)}
        </Link>
      )}
    </AuthLayout>
  );
}
