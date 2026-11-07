// Google sign-in helpers shared by Login and Register: ONE place builds the
// authorize link and ONE place turns the backend's ?error= code into words.
import { currentVisitorId } from "@/lib/visitorId";

/** /api/v1/auth/google/authorize with where to land and which visitor this is.
 *  The visitor id is only attached when the tracker already created one (never
 *  invented here), mirroring email signup. */
export function googleAuthorizeUrl(returnTo = "/dashboard", visitorId = currentVisitorId()) {
  const params = new URLSearchParams();
  if (returnTo && returnTo !== "/dashboard" && returnTo !== "/") params.set("returnTo", returnTo);
  if (visitorId) params.set("visitor_id", visitorId);
  const qs = params.toString();
  return `/api/v1/auth/google/authorize${qs ? `?${qs}` : ""}`;
}

const MESSAGES = {
  google_denied: ["تم إلغاء تسجيل الدخول بجوجل", "Google sign-in was cancelled"],
  google_invalid_state: ["انتهت صلاحية المحاولة، جرّب مرة أخرى", "That attempt expired, please try again"],
  google_not_configured: ["تسجيل الدخول بجوجل غير متاح حالياً", "Google sign-in is not available right now"],
  google_token_exchange: ["تعذّر الاتصال بجوجل، جرّب مرة أخرى", "Could not reach Google, please try again"],
  google_no_token: ["تعذّر الاتصال بجوجل، جرّب مرة أخرى", "Could not reach Google, please try again"],
  google_profile: ["تعذّر قراءة بيانات حسابك من جوجل", "Could not read your Google profile"],
  google_no_email: ["حساب جوجل هذا لا يحتوي على بريد إلكتروني", "This Google account has no email address"],
  google_email_unverified: [
    "بريدك غير مؤكد. أكّده من رسالة التفعيل أو سجّل الدخول بكلمة المرور",
    "Your email is not verified. Confirm it from the activation email or sign in with your password",
  ],
  google_mfa_required: [
    "حسابك محمي بالتحقق بخطوتين. سجّل الدخول بالبريد وكلمة المرور",
    "Your account uses two-step verification. Sign in with your email and password",
  ],
  google_account_unavailable: ["هذا الحساب غير متاح لتسجيل الدخول حالياً", "This account cannot sign in right now"],
};

/** The readable message for a ?error=google_* code, or "" when it is not ours. */
export function googleErrorMessage(search = window.location.search, locale = "ar") {
  const code = new URLSearchParams(search).get("error");
  const pair = code && MESSAGES[code];
  if (!pair) return "";
  return pair[locale === "en" ? 1 : 0];
}
