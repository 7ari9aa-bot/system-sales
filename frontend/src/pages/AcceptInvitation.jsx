import React from "react";
import { Link, useSearchParams } from "react-router-dom";
import { UserPlus, Lock, UserRound, Loader2 } from "lucide-react";
import AuthLayout from "@/components/AuthLayout";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const copy = {
  ar: {
    title: "قبول دعوة مساحة العمل",
    subtitle: "أكمل بياناتك للانضمام إلى مساحة العمل.",
    name: "الاسم الكامل",
    nameHint: "يُستخدم الاسم عند إنشاء حساب جديد؛ بيانات الحساب الموجود لا تتغير.",
    password: "كلمة المرور",
    passwordHint: "تُستخدم كلمة المرور عند إنشاء حساب جديد؛ كلمة مرور الحساب الموجود لا تتغير.",
    submit: "قبول الدعوة",
    working: "جارٍ قبول الدعوة…",
    invalid: "رابط الدعوة غير مكتمل أو منتهي الصلاحية.",
    success: "تم قبول الدعوة. يمكنك تسجيل الدخول الآن.",
    login: "تسجيل الدخول",
  },
  en: {
    title: "Accept workspace invitation",
    subtitle: "Complete your details to join the workspace.",
    name: "Full name",
    nameHint: "Used when creating a new account; an existing account’s details are unchanged.",
    password: "Password",
    passwordHint: "Used when creating a new account; an existing account’s password is unchanged.",
    submit: "Accept invitation",
    working: "Accepting invitation…",
    invalid: "The invitation link is incomplete or expired.",
    success: "Invitation accepted. You can log in now.",
    login: "Log in",
  },
};

export default function AcceptInvitation() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [locale, setLocale] = React.useState(() => {
    try { return window.localStorage.getItem("fh_locale") === "en" ? "en" : "ar"; } catch { return "ar"; }
  });
  const [fullName, setFullName] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState("");
  const [accepted, setAccepted] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const tx = copy[locale];

  async function submit(event) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api("/invitations/accept", {
        method: "POST",
        body: { token, password, full_name: fullName.trim() },
      });
      setAccepted(true);
      setPassword("");
    } catch (err) {
      setError(err?.message || tx.invalid);
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout
      icon={UserPlus}
      title={tx.title}
      subtitle={tx.subtitle}
      footer={accepted ? <Link to="/login" className="auth-link">{tx.login}</Link> : null}
    >
      {!token ? (
        <div className="auth-error" role="alert">{tx.invalid}</div>
      ) : accepted ? (
        <div className="space-y-4">
          <div className="rounded-lg border border-success/30 bg-success/10 px-4 py-3 text-[13px] text-foreground" role="status">{tx.success}</div>
          <Link to="/login" className="auth-btn-primary flex items-center justify-center">{tx.login}</Link>
        </div>
      ) : (
        <>
          {error && <div className="auth-error" role="alert">{error}</div>}
          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="invite-name">{tx.name}</Label>
              <div className="relative">
                <UserRound className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" aria-hidden="true" />
                <Input id="invite-name" autoComplete="name" required minLength={1} value={fullName} onChange={(event) => setFullName(event.target.value)} className="auth-input" />
              </div>
              <p className="text-[11px] text-muted-foreground">{tx.nameHint}</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="invite-password">{tx.password}</Label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" aria-hidden="true" />
                <Input id="invite-password" type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} className="auth-input" />
              </div>
              <p className="text-[11px] text-muted-foreground">{tx.passwordHint}</p>
            </div>
            <Button type="submit" className="auth-btn-primary w-full" disabled={loading}>
              {loading ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />{tx.working}</> : tx.submit}
            </Button>
          </form>
        </>
      )}
      <button type="button" onClick={() => setLocale((value) => value === "ar" ? "en" : "ar")} className="mt-5 w-full text-center text-xs text-muted-foreground hover:text-foreground">
        {locale === "ar" ? "English" : "العربية"}
      </button>
    </AuthLayout>
  );
}
