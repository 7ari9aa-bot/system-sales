/** Labels this screen owns.
 *
 *  `src/lib/t.ts` is another team's file, so the vocabulary the money inputs and
 *  the idempotency notices need lives here, behind the same language-aware proxy
 *  `t` uses (`@/lib/i18n.makeT`) — Arabic first, English fallback, and the
 *  layout direction never flips. Both dictionaries are checked against one
 *  `OrderLabels` shape, so a missing English string is a compile error rather
 *  than an Arabic leak on an English screen. */

import { makeT, type Lang } from "@/lib/i18n";

type OrderLabels = {
  moneyHeading: string;
  discount: string;
  shipping: string;
  tax: string;
  moneyOptional: string;
  subtotal: string;
  grandTotal: string;
  grandTotalHint: string;
  currencyUnknown: string;
  estimateUnreliable: string;
  negative: string;
  not_a_number: string;
  too_precise: (scale: number) => string;
  too_large: string;
  discountTooBig: string;
  conflictTitle: string;
  conflictBody: string;
  conflictAction: string;
  alreadyCreatedTitle: string;
  alreadyCreatedHint: string;
};

const ar: OrderLabels = {
  moneyHeading: "المبالغ الإضافية",
  discount: "الخصم",
  shipping: "الشحن",
  tax: "الضريبة",
  moneyOptional: "مبالغ اختيارية — اتركها فارغة ليحسبها النظام صفرًا",
  subtotal: "إجمالي الأصناف",
  grandTotal: "الإجمالي النهائي",
  grandTotalHint: "إجمالي الأصناف − الخصم + الشحن + الضريبة، بنفس معادلة الخادم",
  currencyUnknown: "لم تُحدَّد عملة مساحة العمل بعد",
  estimateUnreliable: "تعذَّر حساب الإجمالي: سعر أحد الأصناف غير مقروء",
  negative: "المبلغ لا يكون سالبًا",
  not_a_number: "أدخل رقمًا (أرقام ونقطة عشرية فقط)",
  too_precise: (scale: number) =>
    scale === 0
      ? "هذه العملة لا تُكتب بكسور عشرية"
      : `يُسمح بـ ${scale} خانات عشرية كحد أقصى لهذه العملة`,
  too_large: "المبلغ أكبر من الحد الذي يخزنه النظام",
  discountTooBig: "الخصم أكبر من إجمالي الطلب — يرفض النظام طلبًا بإجمالي سالب",
  conflictTitle: "لم يُنشأ طلب جديد",
  conflictBody:
    "رفض الخادم مفتاح الإرسال هذا: إما أن الطلب أُنشئ فعلًا من هذه النافذة، أو أن المسودة تغيّرت بعد الإنشاء، " +
    "أو أن محاولة سابقة بهذا المفتاح انتهت بنتيجة لم يستطع الخادم تسجيلها. " +
    "أغلق النافذة وراجع قائمة الطلبات — لن يُعاد الإرسال بمفتاح جديد لأن ذلك قد يُنشئ الطلب مرة أخرى.",
  conflictAction: "إغلاق النافذة",
  alreadyCreatedTitle: "تم إنشاء الطلب بالفعل",
  alreadyCreatedHint: "أُعيد عرض نتيجة الإرسال الأول، فلم يتكرر إنشاء الطلب.",
};

const en: OrderLabels = {
  moneyHeading: "Amounts",
  discount: "Discount",
  shipping: "Shipping",
  tax: "Tax",
  moneyOptional: "Optional amounts — leave a field blank and the system treats it as zero",
  subtotal: "Line-item subtotal",
  grandTotal: "Grand total",
  grandTotalHint: "Subtotal − discount + shipping + tax, the server's own formula",
  currencyUnknown: "This workspace's currency is not set yet",
  estimateUnreliable: "Total unavailable: a line item's price could not be read",
  negative: "An amount cannot be negative",
  not_a_number: "Enter a number (digits and a decimal point only)",
  too_precise: (scale: number) =>
    scale === 0
      ? "This currency is not written with decimals"
      : `This currency allows at most ${scale} decimal place(s)`,
  too_large: "This amount is larger than the system stores",
  discountTooBig: "The discount exceeds the order total — a negative total is refused",
  conflictTitle: "No new order was created",
  conflictBody:
    "The server rejected this Idempotency-Key: the order was either already created from this dialog, " +
    "or the draft changed after it was created, or an earlier attempt under this key ended in an outcome " +
    "the server could not record. Close this dialog and check the orders list — the request will not be " +
    "resent under a new key, because that could create the order a second time.",
  conflictAction: "Close dialog",
  alreadyCreatedTitle: "Order already created",
  alreadyCreatedHint: "The first response was replayed — the order was not created twice.",
};

const dictionaries: Record<Lang, OrderLabels> = { ar, en };

/** Resolve per access, so a language switch is picked up on the next render. */
export const ot: OrderLabels = makeT(dictionaries);
