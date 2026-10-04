import React, { useState } from "react";
import { Link } from "react-router-dom";
import { KeyRound, Loader2, Mail } from "lucide-react";
import AuthLayout from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { publicApi } from "@/lib/api";
import { useI18n } from "@/lib/marketing-i18n";

const c = (ar, en) => ({ ar, en });
const tx = (copy, locale) => copy[locale];

export default function ForgotPassword() {
  const { locale } = useI18n();
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await publicApi("/auth/password-reset/request", {
        body: { email: email.trim() },
      });
      // The API intentionally gives the same response for existing and
      // unknown accounts; keep the UI equally neutral.
      setSubmitted(true);
    } catch {
      setError(tx(
        c("تعذّر إرسال الطلب الآن. حاول مرة أخرى بعد قليل.", "We couldn't submit the request. Please try again shortly."),
        locale,
      ));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout
      icon={KeyRound}
      title={tx(c("استعادة كلمة المرور", "Reset your password"), locale)}
      subtitle={tx(
        c("أدخل بريدك الإلكتروني وسنرسل لك رابطًا آمنًا لإعادة التعيين.", "Enter your email and we'll send a secure reset link."),
        locale,
      )}
    >
      {error && <div className="auth-error" role="alert" dir="auto">{error}</div>}
      {submitted ? (
        <div className="auth-note" role="status" aria-live="polite">
          <p className="text-[13.5px] leading-[1.8]">
            {tx(
              c("إذا كان البريد مرتبطًا بحساب، ستصلك رسالة فيها خطوات إعادة التعيين.", "If an account is associated with that email, you'll receive reset instructions shortly."),
              locale,
            )}
          </p>
          <button type="button" className="auth-link inline-flex mt-3" onClick={() => setSubmitted(false)}>
            {tx(c("استخدام بريد آخر", "Try another email"), locale)}
          </button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="reset-email" dir="auto">{tx(c("البريد الإلكتروني", "Email"), locale)}</Label>
            <div className="relative">
              <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
              <Input
                id="reset-email"
                type="email"
                name="email"
                autoComplete="email"
                autoFocus
                required
                maxLength={320}
                placeholder="you@example.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className="auth-input"
                dir="ltr"
              />
            </div>
          </div>
          <Button type="submit" className="auth-btn-primary w-full" disabled={loading}>
            {loading ? (
              <><Loader2 className="mr-2 h-4 w-4 animate-spin" />{tx(c("جارٍ الإرسال...", "Sending..."), locale)}</>
            ) : tx(c("إرسال رابط الاستعادة", "Send reset link"), locale)}
          </Button>
        </form>
      )}
      <Link to="/login" className="auth-link inline-flex mt-4">
        {tx(c("رجوع لتسجيل الدخول", "Back to sign in"), locale)}
      </Link>
    </AuthLayout>
  );
}
