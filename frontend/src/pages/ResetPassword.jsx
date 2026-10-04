import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { KeyRound, Loader2, Lock } from "lucide-react";
import AuthLayout from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { publicApi } from "@/lib/api";
import { useI18n } from "@/lib/marketing-i18n";

const c = (ar, en) => ({ ar, en });
const tx = (copy, locale) => copy[locale];

export default function ResetPassword() {
  const { locale } = useI18n();
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [complete, setComplete] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    // The API sends the credential in the URL fragment so it never reaches
    // server access logs or referrer headers. Remove it from browser history
    // as soon as the page reads it.
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    setToken(fragment.get("token") || "");
    if (window.location.hash) {
      window.history.replaceState(
        window.history.state,
        "",
        `${window.location.pathname}${window.location.search}`,
      );
    }
  }, []);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");
    if (password !== confirmPassword) {
      setError(tx(c("كلمتا المرور غير متطابقتين.", "Passwords do not match."), locale));
      return;
    }
    setLoading(true);
    try {
      await publicApi("/auth/password-reset/confirm", {
        body: { token, password },
      });
      setComplete(true);
      setPassword("");
      setConfirmPassword("");
      setToken("");
    } catch (err) {
      const invalidLink = err?.code === "validation_error" || err?.status === 400;
      setError(invalidLink
        ? tx(c("الرابط غير صالح أو انتهت صلاحيته. اطلب رابطًا جديدًا.", "This reset link is invalid or expired. Request a new one."), locale)
        : tx(c("تعذّر تحديث كلمة المرور الآن. حاول مرة أخرى.", "We couldn't update your password. Please try again."), locale));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout
      icon={KeyRound}
      title={tx(c("كلمة مرور جديدة", "Choose a new password"), locale)}
      subtitle={tx(c("أنشئ كلمة مرور جديدة لحماية حسابك.", "Create a new password to secure your account."), locale)}
    >
      {error && <div className="auth-error" role="alert" dir="auto">{error}</div>}
      {complete ? (
        <div className="auth-note" role="status" aria-live="polite">
          <p className="text-[13.5px] leading-[1.8]">
            {tx(c("تم تحديث كلمة المرور. سجّل الدخول بكلمة المرور الجديدة.", "Your password has been updated. Sign in with your new password."), locale)}
          </p>
          <Link to="/login" className="auth-link inline-flex mt-3">
            {tx(c("الانتقال لتسجيل الدخول", "Continue to sign in"), locale)}
          </Link>
        </div>
      ) : !token ? (
        <div className="auth-note">
          <p className="text-[13.5px] leading-[1.8]">
            {tx(c("رابط إعادة التعيين غير موجود أو انتهت صلاحيته.", "The reset link is missing or has expired."), locale)}
          </p>
          <Link to="/forgot-password" className="auth-link inline-flex mt-3">
            {tx(c("اطلب رابطًا جديدًا", "Request a new link"), locale)}
          </Link>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="new-password" dir="auto">{tx(c("كلمة المرور الجديدة", "New password"), locale)}</Label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
              <Input
                id="new-password"
                type="password"
                name="new-password"
                autoComplete="new-password"
                autoFocus
                required
                minLength={8}
                maxLength={128}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="auth-input"
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirm-password" dir="auto">{tx(c("تأكيد كلمة المرور", "Confirm password"), locale)}</Label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
              <Input
                id="confirm-password"
                type="password"
                name="confirm-password"
                autoComplete="new-password"
                required
                minLength={8}
                maxLength={128}
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                className="auth-input"
              />
            </div>
          </div>
          <Button type="submit" className="auth-btn-primary w-full" disabled={loading}>
            {loading ? (
              <><Loader2 className="mr-2 h-4 w-4 animate-spin" />{tx(c("جارٍ الحفظ...", "Saving..."), locale)}</>
            ) : tx(c("حفظ كلمة المرور", "Save new password"), locale)}
          </Button>
        </form>
      )}
      {!complete && (
        <Link to="/login" className="auth-link inline-flex mt-4">
          {tx(c("رجوع لتسجيل الدخول", "Back to sign in"), locale)}
        </Link>
      )}
    </AuthLayout>
  );
}
