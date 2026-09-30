import React from "react";
import { Link } from "react-router-dom";
import { KeyRound } from "lucide-react";
import AuthLayout from "@/components/AuthLayout";
import { useI18n, T } from "@/lib/marketing-i18n";

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
              "كلمنا على البريد وهنرجعلك بحسابك: 7ari9aa@gmail.com",
              "Email us and we'll restore your access: 7ari9aa@gmail.com"
            ),
            locale
          )}
        </p>
        <Link to="/login" className="auth-link inline-flex mt-4">
          {tx(c("رجوع لتسجيل الدخول", "Back to sign in"), locale)}
        </Link>
      </div>
    </AuthLayout>
  );
}
