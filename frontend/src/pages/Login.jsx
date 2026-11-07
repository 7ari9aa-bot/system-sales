import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/lib/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LogIn, Mail, Lock, Loader2, ShieldCheck } from "lucide-react";
import AuthLayout from "@/components/AuthLayout";
import { safeReturnTo } from "@/lib/authReturnTo";
import { googleAuthorizeUrl, googleErrorMessage } from "@/lib/googleAuth";

const c = (ar, en) => ({ ar, en });
const tx = (copy, locale) => copy[locale];

export default function Login() {
  const locale = (() => { try { return window.localStorage.getItem("fh_locale") === "en" ? "en" : "ar" } catch { return "ar" } })();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(() => googleErrorMessage(window.location.search, (() => { try { return window.localStorage.getItem("fh_locale") === "en" ? "en" : "ar" } catch { return "ar" } })()));
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
        <div className="relative my-4">
          <div className="absolute inset-0 flex items-center"><span className="w-full border-t border-border" /></div>
          <div className="relative flex justify-center text-xs"><span className="bg-card px-2 text-muted-foreground">{tx(c("أو", "or"), locale)}</span></div>
        </div>
        <a
          href={googleAuthorizeUrl(returnTo)}
          className="flex items-center justify-center gap-2 w-full rounded-md border border-border bg-background px-4 py-2 text-sm font-medium transition-colors hover:bg-accent"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" className="shrink-0">
            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
          </svg>
          {tx(c("تسجيل الدخول بجوجل", "Sign in with Google"), locale)}
        </a>
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
