import React from "react";
import { Link } from "react-router-dom";
import { KeyRound } from "lucide-react";
import AuthLayout from "@/components/AuthLayout";
import { useI18n } from "@/lib/marketing-i18n";

const c = (ar, en) => ({ ar, en });
const tx = (copy, locale) => copy[locale];

/** استعادة كلمة المرور — الـbackend مش بينشر مسار reset لسه،
 *  فالصفحة بتعكس الحقيقة: تواصل مباشر، بدون نموذج وهمي. */
export default function ForgotPassword() {
  const { locale } = useI18n();
  return (
    <AuthLayout
      icon={KeyRound}
      title={tx(c("استعادة كلمة المرور", "Reset your password"), locale)}
      subtitle={tx(
        c("الخدمة دي لسه مش متاحة في النسخة الحالية.", "This isn't available in the current version yet."),
        locale
      )}
    >
      <div className="auth-note">
        <p className="text-[13.5px] leading-[1.8]">
          {tx(
            c(
              "كلمنا على البريد وهنساعدك ترجع لحسابك:",
              "Email us and we'll help you recover your account:"
            ),
            locale
          )}
        </p>
        <a href="mailto:7ari9aa@gmail.com" className="auth-link inline-flex mt-2" dir="ltr">
          7ari9aa@gmail.com
        </a>
        <Link to="/login" className="auth-link inline-flex mt-4">
          {tx(c("رجوع لتسجيل الدخول", "Back to sign in"), locale)}
        </Link>
      </div>
    </AuthLayout>
  );
}
