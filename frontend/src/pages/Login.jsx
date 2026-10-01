import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/lib/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LogIn, Mail, Lock, Loader2, ShieldCheck } from "lucide-react";
import AuthLayout from "@/components/AuthLayout";
import { safeReturnTo } from "@/lib/authReturnTo";

const c = (ar, en) => ({ ar, en });
const tx = (copy, locale) => copy[locale];

export default function Login() {
  const locale = (() => { try { return window.localStorage.getItem("fh_locale") === "en" ? "en" : "ar" } catch { return "ar" } })();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [challengeId, setChallengeId] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [useBackupCode, setUseBackupCode] = useState(false);
  const { login, verifyMfa } = useAuth();
  const [loading, setLoading] = useState(false);
  const returnTo = safeReturnTo();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (challengeId) {
        await verifyMfa(challengeId, mfaCode.trim());
      } else {
        const result = await login(email, password);
        if (result?.requiresMfa) {
          setChallengeId(result.challengeId);
          setMfaCode("");
          return;
        }
      }
      window.location.href = returnTo;
    } catch (err) {
      setError(err.message || tx(c("بريد إلكتروني أو كلمة مرور غير صحيحة", "Invalid email or password"), locale));
    } finally {
      setLoading(false);
    }
  };


  return (
    <AuthLayout
      icon={LogIn}
      title={tx(c("مرحباً بعودتك", "Welcome back"), locale)}
      subtitle={tx(c("سجّل الدخول إلى حسابك", "Log in to your account"), locale)}
      footer={
        <>
          {tx(c("ليس لديك حساب؟ ", "Don't have an account? "), locale)}
          <Link to={"/register" + (returnTo !== "/" ? "?returnTo=" + encodeURIComponent(returnTo) : "")} className="auth-link">{tx(c("أنشئ واحداً", "Create one"), locale)}</Link>
        </>
      }
    >
            <div className="auth-divider"><span>{tx(c("أو", "or"), locale)}</span></div>
      {error && <div className="auth-error" dir="auto">{error}</div>}
      {!challengeId ? <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="email" dir="auto">{tx(c("البريد الإلكتروني", "Email"), locale)}</Label>
          <div className="relative">
            <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
            <Input id="email" type="email" autoComplete="email" autoFocus placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} className="auth-input" required />
          </div>
        </div>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="password" dir="auto">{tx(c("كلمة المرور", "Password"), locale)}</Label>
            <Link to="/forgot-password" className="auth-link text-xs">{tx(c("نسيت كلمة المرور؟", "Forgot password?"), locale)}</Link>
          </div>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
            <Input id="password" type="password" autoComplete="current-password" placeholder="••••••••" value={password} onChange={(e) => setPassword(e.target.value)} className="auth-input" required />
          </div>
        </div>
        <Button type="submit" className="auth-btn-primary" disabled={loading}>
          {loading ? (<><Loader2 className="w-4 h-4 mr-2 animate-spin" />{tx(c("جارٍ الدخول...", "Logging in..."), locale)}</>) : tx(c("تسجيل الدخول", "Log in"), locale)}
        </Button>
      </form> : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="rounded-lg border border-border bg-surface/50 p-3 text-[12px] text-muted-foreground">
            <ShieldCheck className="mr-1 inline h-4 w-4" />
            {tx(c("أدخل رمز تطبيق المصادقة أو رمز استرداد لمرة واحدة.", "Enter an authenticator code or a one-time recovery code."), locale)}
          </div>
          <div className="space-y-2">
            <Label htmlFor="mfa-code">{tx(c("رمز التحقق", "Verification code"), locale)}</Label>
            <Input
              id="mfa-code"
              inputMode={useBackupCode ? "text" : "numeric"}
              autoComplete={useBackupCode ? "off" : "one-time-code"}
              pattern={useBackupCode ? "[a-fA-F0-9]{16}" : "[0-9]{6}"}
              maxLength={useBackupCode ? 16 : 6}
              required
              autoFocus
              value={mfaCode}
              onChange={(event) => setMfaCode(useBackupCode ? event.target.value.replace(/[^a-fA-F0-9]/g, "").slice(0, 16) : event.target.value.replace(/\D/g, ""))}
              className="auth-input"
              dir="ltr"
            />
          </div>
          <button type="button" onClick={() => { setUseBackupCode((value) => !value); setMfaCode(""); }} className="text-xs text-primary hover:underline">
            {useBackupCode ? tx(c("استخدام رمز تطبيق المصادقة", "Use authenticator code"), locale) : tx(c("استخدام رمز استرداد", "Use recovery code"), locale)}
          </button>
          <Button type="submit" className="auth-btn-primary w-full" disabled={loading || mfaCode.length !== (useBackupCode ? 16 : 6)}>
            {loading ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />{tx(c("جارٍ التحقق...", "Verifying..."), locale)}</> : tx(c("تأكيد وتسجيل الدخول", "Verify and log in"), locale)}
          </Button>
          <button type="button" onClick={() => { setChallengeId(""); setMfaCode(""); setError(""); }} className="w-full text-center text-xs text-muted-foreground hover:text-foreground">
            {tx(c("العودة إلى تسجيل الدخول", "Back to log in"), locale)}
          </button>
        </form>
      )}
    </AuthLayout>
  );
}
