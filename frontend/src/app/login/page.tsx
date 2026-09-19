import { redirect } from "next/navigation";

/** تسجيل الدخول انتقل إلى /auth/login — توجيه من السيرفر بدون وميض. */
export default function LoginRedirect() {
  redirect("/auth/login");
}
