import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/lib/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { UserPlus, Mail, Lock, Loader2 } from "lucide-react";
import AuthLayout from "@/components/AuthLayout";
import { safeReturnTo } from "@/lib/authReturnTo";

const c = (ar, en) => ({ ar, en });
const tx = (copy, locale) => copy[locale];

export default function Register() {
  const locale = (() => { try { return window.localStorage.getItem("fh_locale") === "en" ? "en" : "ar" } catch { return "ar" } })();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const { register, login } = useAuth();
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (password !== confirmPassword) {
      setError(tx(c("كلمتا المرور غير متطابقتين", "Passwords do not match"), locale));
      return;
    }
    setLoading(true);
    try {
      await register({ email, password });
      await login(email, password);
      window.location.href = safeReturnTo();
    } catch (err) {
      setError(err.message || tx(c("فشل التسجيل", "Registration failed"), locale));
    } finally {
      setLoading(false);
    }
  };




  return (
    <AuthLayout
      icon={UserPlus}
      title={tx(c("أنشئ حسابك", "Create your account"), locale)}
      subtitle={tx(c("سجّل للبدء مع FIHRIST", "Sign up to get started"), locale)}
      footer={
        <>
          {tx(c("لديك حساب بالفعل؟ ", "Already have an account? "), locale)}
          <Link to={"/login" + (safeReturnTo() !== "/" ? "?returnTo=" + encodeURIComponent(safeReturnTo()) : "")} className="auth-link">{tx(c("تسجيل الدخول", "Log in"), locale)}</Link>
        </>
      }
    >
            <div className="auth-divider"><span>{tx(c("أو", "or"), locale)}</span></div>
      {error && <div className="auth-error" dir="auto">{error}</div>}
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="email" dir="auto">{tx(c("البريد الإلكتروني", "Email"), locale)}</Label>
          <div className="relative">
            <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
            <Input id="email" type="email" autoComplete="email" autoFocus placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} className="auth-input" required />
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor="password" dir="auto">{tx(c("كلمة المرور", "Password"), locale)}</Label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
            <Input id="password" type="password" autoComplete="new-password" placeholder="••••••••" value={password} onChange={(e) => setPassword(e.target.value)} className="auth-input" required />
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor="confirm" dir="auto">{tx(c("تأكيد كلمة المرور", "Confirm Password"), locale)}</Label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
            <Input id="confirm" type="password" autoComplete="new-password" placeholder="••••••••" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} className="auth-input" required />
          </div>
        </div>
        <Button type="submit" className="auth-btn-primary" disabled={loading}>
          {loading ? (<><Loader2 className="w-4 h-4 mr-2 animate-spin" />{tx(c("جارٍ الإنشاء...", "Creating account..."), locale)}</>) : tx(c("إنشاء الحساب", "Create account"), locale)}
        </Button>
        <div className="relative my-4">
          <div className="absolute inset-0 flex items-center"><span className="w-full border-t border-border" /></div>
          <div className="relative flex justify-center text-xs"><span className="bg-card px-2 text-muted-foreground">{tx(c("أو", "or"), locale)}</span></div>
        </div>
        <a
          href="/api/v1/auth/google/authorize"
          className="flex items-center justify-center gap-2 w-full rounded-md border border-border bg-background px-4 py-2 text-sm font-medium transition-colors hover:bg-accent"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" className="shrink-0">
            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
          </svg>
          {tx(c("التسجيل بجوجل", "Sign up with Google"), locale)}
        </a>
      </form>
    </AuthLayout>
  );
}