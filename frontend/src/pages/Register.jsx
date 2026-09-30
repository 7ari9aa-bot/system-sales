import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/lib/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { UserPlus, Mail, Lock, Loader2 } from "lucide-react";
import { InputOTP, InputOTPGroup, InputOTPSlot } from "@/components/ui/input-otp";
import AuthLayout from "@/components/AuthLayout";
import GoogleIcon from "@/components/GoogleIcon";
import { toast } from "@/components/ui/use-toast";
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
      <Button variant="outline" className="auth-btn-google" onClick={handleGoogle}>
        <GoogleIcon className="w-5 h-5 mr-2" />
        {tx(c("المتابعة عبر Google", "Continue with Google"), locale)}
      </Button>
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
      </form>
    </AuthLayout>
  );
}