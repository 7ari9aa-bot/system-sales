/** Labels the approvals screen owns.
 *
 *  Same shape the orders surface uses (`../orders/labels.ts`): one `ApprovalLabels`
 *  type, an `ar` and an `en` object checked against it, resolved through the
 *  language-aware proxy `@/lib/i18n.makeT` — Arabic first, English fallback, the
 *  layout direction never flips. Both dictionaries satisfy one type, so a missing
 *  English string is a compile error rather than an Arabic leak on an English
 *  screen, and no user-facing sentence is hardcoded in JSX.
 *
 *  `@/lib/t` already carries a partial approvals vocabulary, but it is another
 *  team's file and it lacks the decision dialog and the refusal notices this
 *  screen needs; those live here so the whole vocabulary the approvals page
 *  renders is owned, typed and bilingual in one place. */

import { makeT, type Lang } from "@/lib/i18n";
import { APPROVALS_PAGE_SIZE } from "./decision";

type ApprovalLabels = {
  /* --------------------------------------------------------------- the screen */
  title: string;
  subtitle: string;
  loading: string;
  pendingCount: (n: number) => string;

  tabPending: string;
  tabApproved: string;
  tabRejected: string;

  /** The page is bounded; this is the screen admitting it is showing a prefix. */
  queueTruncated: string;

  riskHigh: string;
  riskMedium: string;
  riskLow: string;

  statusPending: string;
  statusApproved: string;
  statusRejected: string;
  statusExpired: string;
  statusCancelled: string;

  requestedBy: string;
  when: string;
  expires: string;
  noExpiry: string;
  argumentsHeading: string;
  argumentsEmpty: string;
  rejectionReasonHeading: string;

  approve: string;
  reject: string;

  pendingEmptyTitle: string;
  pendingEmptyHint: string;
  resolvedEmptyTitle: string;
  resolvedEmptyHint: string;

  /* -------------------------------------------------------------- the dialog */
  approveTitle: string;
  approveBody: string;
  approveSubmit: string;
  denyTitle: string;
  denyBody: string;
  denySubmit: string;
  reasonLabel: string;
  reasonHint: string;
  reasonTooLong: string;
  cancel: string;
  approveDone: string;
  denyDone: string;
  resumedNote: string;

  /* --------------------------------------------------- the server's refusals */
  refusedTitle: string;
  refusedHint: string;
  /** `require_permission("settings:write")` gates the decide route (router.py:324). */
  permissionTitle: string;
  /** The key is spent / the approval left PENDING: stop, do not re-mint, re-read. */
  terminalTitle: string;
  terminalBody: string;
  terminalAction: string;
  networkTitle: string;
  serverTitle: string;
};

const ar: ApprovalLabels = {
  title: "الموافقات",
  subtitle: "إجراءات الذكاء الاصطناعي عالية المخاطر بانتظار قرار بشري (§135)",
  loading: "جارٍ التحميل",
  pendingCount: (n: number) => `بانتظار قرارك (${n})`,

  tabPending: "بانتظار القرار",
  tabApproved: "الموافق عليها",
  tabRejected: "المرفوضة",

  queueTruncated:
    "تعرض هذه الصفحة أقدم " +
    APPROVALS_PAGE_SIZE +
    " طلبًا في هذا التصنيف فقط — لا تزال هناك موافقات أخرى معلّقة. قراراتك في هذه الصفحة تُفتح أولًا، ثم تُعاد القراءة.",

  riskHigh: "عالية",
  riskMedium: "متوسطة",
  riskLow: "منخفضة",

  statusPending: "بانتظار الموافقة",
  statusApproved: "تمت الموافقة",
  statusRejected: "مرفوض",
  statusExpired: "منتهي",
  statusCancelled: "ملغي",

  requestedBy: "طالب الإجراء",
  when: "وقت الطلب",
  expires: "تنتهي",
  noExpiry: "بدون وقت انتهاء",
  argumentsHeading: "الوسائط المرتبطة بهذا القرار",
  argumentsEmpty: "لا وسائط مسجّلة لهذا الإجراء",
  rejectionReasonHeading: "سبب الرفض",

  approve: "موافقة",
  reject: "رفض",

  pendingEmptyTitle: "لا موافقات معلّقة",
  pendingEmptyHint: "لا إجراءات عالية الخطورة بانتظار قرارك الآن.",
  resolvedEmptyTitle: "لا شيء في هذه القائمة بعد",
  resolvedEmptyHint: "لم يُتَّخذ قرار بهذا التصنيف بعد.",

  approveTitle: "الموافقة على الإجراء؟",
  approveBody: "سيُنفَّذ إجراء الذكاء الاصطناعي عالي المخاطر بهذه الوسائط فور موافقتك. لا يمكن التراجع.",
  approveSubmit: "تأكيد الموافقة",
  denyTitle: "رفض الإجراء؟",
  denyBody: "سيُغلق الطلب مرفوضًا ولن يُنفَّذ الإجراء. لا يمكن التراجع.",
  denySubmit: "تأكيد الرفض",
  reasonLabel: "سبب الرفض (اختياري)",
  reasonHint: "يُحفظ مع الطلب — 512 حرفًا كحد أقصى؛ اتركه فارغًا لعدم تسجيل سبب",
  reasonTooLong: "السبب أطول من 512 حرفًا، سيرفضه الخادم",
  cancel: "إلغاء",
  approveDone: "تمت الموافقة على الإجراء",
  denyDone: "تم رفض الإجراء",
  resumedNote: "أُعيد جدولزة المحادثة لتنفيذ الإجراء",

  refusedTitle: "رفض الخادم هذا القرار",
  refusedHint: "لم يُنفَّذ شيء. صحّح وأعد المحاولة بنفس مفتاح الإرسال.",
  permissionTitle: "لا صلاحية لديك لاتخاذ هذا القرار (settings:write)",
  terminalTitle: "لا يمكن إرسال هذا القرار",
  terminalBody:
    "انتهت هذه الموافقة في السجل: بَتَّ فيها قرار سابق، أو انتهت صلاحيتها، أو لم تعد موجودة. " +
    "لن يُصدر مفتاح جديد لأن إعادة إرسال قرار الموافقة قد تمنح نفس الإجراء مرتين — " +
    "أغلق النافذة وأعد قراءة قائمة الموافقات.",
  terminalAction: "إغلاق النافذة",
  networkTitle: "لم يصل الطلب إلى الخادم",
  serverTitle: "خطأ غير متوقع من الخادم",
};

const en: ApprovalLabels = {
  title: "Approvals",
  subtitle: "High-risk AI actions awaiting a human decision (§135)",
  loading: "Loading",
  pendingCount: (n: number) => `Awaiting your decision (${n})`,

  tabPending: "Pending",
  tabApproved: "Approved",
  tabRejected: "Rejected",

  queueTruncated:
    "This page shows the oldest " +
    APPROVALS_PAGE_SIZE +
    " requests in this state — other approvals are still waiting. Decide what is here and this list re-reads.",

  riskHigh: "High",
  riskMedium: "Medium",
  riskLow: "Low",

  statusPending: "Awaiting approval",
  statusApproved: "Approved",
  statusRejected: "Rejected",
  statusExpired: "Expired",
  statusCancelled: "Cancelled",

  requestedBy: "Requested by",
  when: "Requested on",
  expires: "Expires",
  noExpiry: "No expiry",
  argumentsHeading: "Arguments this decision is bound to",
  argumentsEmpty: "No arguments recorded for this action",
  rejectionReasonHeading: "Rejection reason",

  approve: "Approve",
  reject: "Reject",

  pendingEmptyTitle: "No pending approvals",
  pendingEmptyHint: "No high-risk actions are waiting for your decision right now.",
  resolvedEmptyTitle: "Nothing in this list yet",
  resolvedEmptyHint: "No decision has been recorded under this status yet.",

  approveTitle: "Approve this action?",
  approveBody: "The high-risk AI action will run with these arguments the moment you approve. This cannot be undone.",
  approveSubmit: "Confirm approval",
  denyTitle: "Reject this action?",
  denyBody: "The request will be closed as rejected and the action will not run. This cannot be undone.",
  denySubmit: "Confirm rejection",
  reasonLabel: "Rejection reason (optional)",
  reasonHint: "Stored with the request — 512 characters maximum; leave it empty to record no reason",
  reasonTooLong: "This reason is longer than 512 characters, and the server refuses it",
  cancel: "Cancel",
  approveDone: "Action approved",
  denyDone: "Action rejected",
  resumedNote: "The conversation was re-queued to run the action",

  refusedTitle: "The server refused this decision",
  refusedHint: "Nothing ran. Fix it and try again under the same submission key.",
  permissionTitle: "You do not have permission to decide this (settings:write)",
  terminalTitle: "This decision cannot be sent",
  terminalBody:
    "This approval has ended in the record: an earlier decision settled it, it expired, or it no longer exists. " +
    "A new key will not be minted, because replaying an approval could grant the same action twice — " +
    "close this dialog and re-read the approvals list.",
  terminalAction: "Close dialog",
  networkTitle: "The request never reached the server",
  serverTitle: "Unexpected server error",
};

const dictionaries: Record<Lang, ApprovalLabels> = { ar, en };

/** Resolve per access, so a language switch is picked up on the next render. */
export const ap: ApprovalLabels = makeT(dictionaries);
