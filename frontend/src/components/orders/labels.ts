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

  /* ---------------------------- order record: the operations surface ---- */
  backToOrders: string;
  orderNotFound: string;
  /** The two axes, labelled so a merchant reads them as two facts, not one. */
  lifecycleStatus: string;
  refundAxis: string;
  refundStateHint: string;
  moneyPosition: string;
  collectedGross: string;
  refundedTotal: string;
  netCollected: string;
  lineItems: string;
  operations: string;

  paymentsHeading: string;
  paymentsEmpty: string;
  paymentsEmptyHint: string;
  paymentsUnavailable: string;
  paymentAmount: string;
  paymentMethod: string;
  paymentStatus: string;
  paymentPaidAt: string;
  paymentProvider: string;
  paymentProviderRef: string;
  /** A payment that is not a capture cannot be refunded (§ `register_refund`). */
  cannotRefund: string;
  refundAction: string;

  historyHeading: string;
  historyEmpty: string;
  /** The fallback sentence when the history read is down and the server gave none. */
  historyUnavailable: string;
  historyFrom: string;
  historyTo: string;
  historyNote: string;
  historyWhen: string;

  refundTitle: string;
  refundDescription: string;
  refundAmountLabel: string;
  refundReasonLabel: string;
  refundReasonHint: string;
  /** `Captured 250.00 EGP` — the ceiling the dialog may state, and only state
   *  when the read actually makes it computable. */
  refundCaptured: (amount: string) => string;
  refundCapUnknown: string;
  refundAmountEmpty: string;
  refundAmountZero: string;
  refundOverCaptured: (amount: string) => string;
  refundReasonTooLong: string;
  refundDoneTitle: string;
  refundDoneHint: string;

  cancelTitle: string;
  cancelDescription: string;
  cancelWarning: string;
  cancelNoteLabel: string;
  cancelNoteHint: string;
  cancelNoteTooLong: string;
  cancelAck: string;
  cancelSubmit: string;
  cancelDoneHint: string;

  returnTitle: string;
  returnDescription: string;
  returnReasonLabel: string;
  returnReasonCustomer: string;
  returnReasonDelivery: string;
  returnSubmit: string;
  /** ADR-052: the return saga restocks goods and moves the lifecycle. It does
   *  not touch money, and a merchant who expects the refund to ride along on
   *  the return has to be told otherwise. */
  returnMoneyNote: string;
  returnDoneTitle: string;
  returnDoneHint: string;
  returnSaga: (status: string) => string;

  shippingTitle: string;
  shippingDescription: string;
  shippingMethodLabel: string;
  shippingMethodHint: string;
  shippingAddressLabel: string;
  shippingAddressHint: string;
  /** The four refusals `buildShippingPayload` can raise. */
  shippingNothing: string;
  shippingInvalidJson: string;
  shippingNotObject: string;
  shippingMethodTooLong: string;
  shippingSubmit: string;
  shippingDoneTitle: string;
  shippingDoneHint: string;
  /** A lost conditional write: re-read, never overwrite. */
  shippingStaleTitle: string;
  shippingReread: string;
  shippingVersion: (version: number) => string;

  /** A write the server refused. The server's own sentence is always shown:
   *  `refusedHint` explains what the merchant may do next. */
  refusedTitle: string;
  refusedHint: string;
  permissionTitle: string;
  /** A terminal 409/412: the key is spent, so the dialog stops sending. */
  terminalTitle: string;
  terminalBody: string;
  terminalAction: string;
  networkTitle: string;

  /** The two captions the operation dialogs need beyond their own titles. */
  cancelAction: string;
  refundSubmit: string;
  /** The three record-page buttons. Short by design: the dialog carries the rule. */
  cancelBtn: string;
  returnBtn: string;
  shippingBtn: string;
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

  /* -------------------------- order record: the operations surface ------ */
  backToOrders: "العودة إلى الطلبات",
  orderNotFound: "لم يمكن قراءة هذا الطلب",
  lifecycleStatus: "حالة الطلب",
  refundAxis: "حالة الاسترداد",
  refundStateHint: "المال المرتجع محور مستقل عن حالة الطلب: أحدهما لا يمحو الآخر",
  moneyPosition: "المركز المالي",
  collectedGross: "إجمالي الطلب",
  refundedTotal: "المُستَرَّد",
  netCollected: "الصافي المحصَّل",
  lineItems: "أصناف الطلب",
  operations: "إجراءات الطلب",

  paymentsHeading: "الدفعات",
  paymentsEmpty: "لا مدفوعات مسجّلة على هذا الطلب",
  paymentsEmptyHint: "تُسجَّل الدفعة عند تحصيل المال فعليًا، ومن هنا يبدأ مسار الاسترداد.",
  paymentsUnavailable: "تعذَّر قراءة سجل الدفعات",
  paymentAmount: "المبلغ",
  paymentMethod: "الطريقة",
  paymentStatus: "الحالة",
  paymentPaidAt: "وقت الدفع",
  paymentProvider: "المزوّد",
  paymentProviderRef: "مرجع المزوّد",
  cannotRefund: "لم تُحصَّل هذه الدفعة بعد، فلا يمكن استردادها",
  refundAction: "استرداد",

  historyHeading: "سجل الحالات",
  historyEmpty: "لا انتقالات مسجّلة بعد",
  historyUnavailable: "لم يبلغ الخادم عن سبب — تعذّر قراءة سجل الحالات",
  historyFrom: "من",
  historyTo: "إلى",
  historyNote: "ملاحظة",
  historyWhen: "التوقيت",

  refundTitle: "استرداد مبلغ",
  refundDescription:
    "يُسجَّل الاسترداد على هذه الدفعة تحديدًا، ثم يُقرأ المركز المالي للطلب من الدفاتر — لا من هذه الشاشة.",
  refundAmountLabel: "المبلغ المسترد",
  refundReasonLabel: "السبب (اختياري)",
  refundReasonHint: "يُحفظ مع حركة المال كما كُتب",
  refundCaptured: (amount: string) => `المحصَّل في هذه الدفعة: ${amount}`,
  refundCapUnknown:
    "لا يمكن حساب المتبقي من هذه الدفعة هنا: سجل الاستردادات لا يُقرأ مع الدفعة. " +
    "الخادم هو من يرفض الزائد — بكلمته هو.",
  refundAmountEmpty: "أدخل مبلغًا للاسترداد",
  refundAmountZero: "الاسترداد لا يكون صفرًا",
  refundOverCaptured: (amount: string) => `المبلغ أكبر من المحصَّل في هذه الدفعة (${amount})`,
  refundReasonTooLong: "السبب أطول من الحد الذي يخزنه النظام (512 حرفًا)",
  refundDoneTitle: "تم تسجيل الاسترداد",
  refundDoneHint: "أُعيد قراءة المركز المالي للطلب من الدفاتر",

  cancelTitle: "إلغاء الطلب",
  cancelDescription: "الإلغاء يُطلق المخزون المحجوز ويسجّل سببه في سجل الحالات.",
  cancelWarning: "لا يمكن التراجع عن إلغاء الطلب: سيُغلق، ويبقى السبب في السجل.",
  cancelNoteLabel: "سبب الإلغاء (اختياري)",
  cancelNoteHint: "يُحفظ في سجل الحالات — 512 حرفًا كحد أقصى",
  cancelNoteTooLong: "السبب أطول من 512 حرفًا، ولن يُحفظ على أي حال",
  cancelAck: "أفهم أن إلغاء الطلب لا يمكن التراجع عنه",
  cancelSubmit: "تأكيد الإلغاء",
  cancelDoneHint: "أُطلق المخزون المحجوز وسُجِّل الانتقال بسببه",

  returnTitle: "إرجاع الطلب",
  returnDescription: "تعود البضاعة إلى المخزون ثم يُغلق الطلب، عبر عملية مُنسَّقة بخطوتين.",
  returnReasonLabel: "سبب الإرجاع",
  returnReasonCustomer: "إرجاع من العميل",
  returnReasonDelivery: "تعذّر التوصيل",
  returnSubmit: "تأكيد الإرجاع",
  returnMoneyNote: "الإرجاع يعرض البضاعة للمخزون ولا يمس المال: الاسترداد إجراء مستقل على الدفعة.",
  returnDoneTitle: "تم إرجاع الطلب",
  returnDoneHint: "أُعيدت البضاعة للمخزون وأُغلق الطلب",
  returnSaga: (status: string) => `نتيجة العملية: ${status}`,

  shippingTitle: "تعديل بيانات الشحن",
  shippingDescription: "تصحيح عنوان أو طريقة شحن طلب لم يغادر بعد — لا يغيّر حالة الطلب.",
  shippingMethodLabel: "طريقة الشحن",
  shippingMethodHint: "حتى 31 حرفًا — اتركها فارغة لتبقى كما هي",
  shippingAddressLabel: "العنوان (JSON)",
  shippingAddressHint: "العنوان يُستبدل بالكامل: أرسله كما يجب أن يبدو للعميل بعد التعديل",
  shippingNothing: "لم يتغيّر شيء — لا يُرسل تعديل فارغ",
  shippingInvalidJson: "العنوان ليس JSON صحيحًا",
  shippingNotObject: "العنوان يجب أن يكون object، لا قائمة ولا قيمة مفردة",
  shippingMethodTooLong: "طريقة الشحن أطول من 31 حرفًا",
  shippingSubmit: "حفظ التعديل",
  shippingDoneTitle: "تم تحديث الشحن",
  shippingDoneHint: "زادت نسخة الطلب: كل تعديل لاحق يبدأ من النسخة الجديدة",
  shippingStaleTitle: "تغيّر الطلب بعد قراءته — لن يُكتب تعديلك فوق تعديل غيرك",
  shippingReread: "إعادة قراءة الطلب",
  shippingVersion: (version: number) => `النسخة ${version}`,

  refusedTitle: "رفض الخادم الطلب",
  refusedHint: "لم يُنفَّذ شيء. صحّح وأعد المحاولة بنفس مفتاح الإرسال.",
  permissionTitle: "لا صلاحية لديك لهذا الإجراء (orders:write)",
  terminalTitle: "لم يُعَد الإرسال",
  terminalBody:
    "انتهت هذه المحاولة عند الخادم: استُخدم مفتاح الإرسال من قبل، أو أن الإجراء نفّذته محاولة سابقة. " +
    "لن يُصدر مفتاح جديد لأن ذلك قد يعيد نفس الإجراء — أغلق النافذة واقرأ الطلب من جديد.",
  terminalAction: "إغلاق النافذة",
  networkTitle: "لم يصل الطلب إلى الخادم",
  cancelAction: "إلغاء",
  refundSubmit: "تسجيل الاسترداد",
  cancelBtn: "إلغاء الطلب",
  returnBtn: "إرجاع الطلب",
  shippingBtn: "تعديل الشحن",
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

  /* -------------------------- order record: the operations surface ------ */
  backToOrders: "Back to orders",
  orderNotFound: "This order could not be read",
  lifecycleStatus: "Order status",
  refundAxis: "Refund state",
  refundStateHint: "Money given back is its own axis: it never overwrites where the parcel is",
  moneyPosition: "Money position",
  collectedGross: "Order total",
  refundedTotal: "Refunded",
  netCollected: "Net collected",
  lineItems: "Line items",
  operations: "Order actions",

  paymentsHeading: "Payments",
  paymentsEmpty: "No payment recorded on this order",
  paymentsEmptyHint: "A payment is recorded when money is actually captured — that is also what a refund can target.",
  paymentsUnavailable: "The payment ledger could not be read",
  paymentAmount: "Amount",
  paymentMethod: "Method",
  paymentStatus: "Status",
  paymentPaidAt: "Paid at",
  paymentProvider: "Provider",
  paymentProviderRef: "Provider ref",
  cannotRefund: "This payment was never captured, so it cannot be refunded",
  refundAction: "Refund",

  historyHeading: "Status history",
  historyEmpty: "No transition recorded yet",
  historyUnavailable: "The server gave no reason — the status history could not be read",
  historyFrom: "From",
  historyTo: "To",
  historyNote: "Note",
  historyWhen: "When",

  refundTitle: "Refund this payment",
  refundDescription:
    "The refund is registered against this payment alone; the order's money position is then re-read from the ledger, not computed here.",
  refundAmountLabel: "Amount to refund",
  refundReasonLabel: "Reason (optional)",
  refundReasonHint: "Stored with the money movement, verbatim",
  refundCaptured: (amount: string) => `Captured on this payment: ${amount}`,
  refundCapUnknown:
    "The remainder of this payment cannot be computed here: the refund ledger is not part of the payment read. " +
    "Enter what you mean — the server refuses an excess, in its own words.",
  refundAmountEmpty: "Enter an amount to refund",
  refundAmountZero: "A refund cannot be zero",
  refundOverCaptured: (amount: string) => `This exceeds the ${amount} captured on this payment`,
  refundReasonTooLong: "This reason is longer than the 512 characters the ledger stores",
  refundDoneTitle: "Refund recorded",
  refundDoneHint: "The order's money position was re-read from the ledger",

  cancelTitle: "Cancel this order",
  cancelDescription: "Cancelling releases the reserved stock and records the reason in the status history.",
  cancelWarning: "Cancelling an order cannot be undone: it closes, and the reason stays in the record.",
  cancelNoteLabel: "Reason (optional)",
  cancelNoteHint: "Saved in the status history — 512 characters maximum",
  cancelNoteTooLong: "This reason is longer than 512 characters, and would not be stored anyway",
  cancelAck: "I understand that cancelling cannot be undone",
  cancelSubmit: "Confirm cancellation",
  cancelDoneHint: "Reserved stock was released and the transition recorded its reason",

  returnTitle: "Return this order",
  returnDescription: "The goods go back to stock and the order closes, as a two-step process.",
  returnReasonLabel: "Return reason",
  returnReasonCustomer: "Customer return",
  returnReasonDelivery: "Delivery failed",
  returnSubmit: "Confirm return",
  returnMoneyNote: "A return restocks goods and does not touch money: a refund is a separate action on a payment.",
  returnDoneTitle: "Order returned",
  returnDoneHint: "Stock was restored and the order closed",
  returnSaga: (status: string) => `Process outcome: ${status}`,

  shippingTitle: "Correct the shipping details",
  shippingDescription: "Fixes the address or method of an order that has not left. It is not a status change.",
  shippingMethodLabel: "Shipping method",
  shippingMethodHint: "Up to 31 characters — leave it empty to keep what is stored",
  shippingAddressLabel: "Address (JSON)",
  shippingAddressHint: "The address is replaced WHOLE: send it as it should read after the correction",
  shippingNothing: "Nothing to change — an empty correction is not sent",
  shippingInvalidJson: "This address is not valid JSON",
  shippingNotObject: "The address must be a JSON object, not a list or a bare value",
  shippingMethodTooLong: "The shipping method is longer than 31 characters",
  shippingSubmit: "Save correction",
  shippingDoneTitle: "Shipping updated",
  shippingDoneHint: "The order's version moved on: the next correction starts from the new one",
  shippingStaleTitle: "The order changed after you read it — your correction will not be written over someone else's",
  shippingReread: "Re-read the order",
  shippingVersion: (version: number) => `version ${version}`,

  refusedTitle: "The server refused this",
  refusedHint: "Nothing ran. Fix it and try again under the same submission key.",
  permissionTitle: "This action needs a permission you do not have (orders:write)",
  terminalTitle: "Not resent",
  terminalBody:
    "This attempt ended at the server: the submission key was already used, or an earlier attempt performed the action. " +
    "A new key will not be minted, because that could run the same action again — close this dialog and re-read the order.",
  terminalAction: "Close dialog",
  networkTitle: "The request never reached the server",
  cancelAction: "Cancel",
  refundSubmit: "Record refund",
  cancelBtn: "Cancel order",
  returnBtn: "Return order",
  shippingBtn: "Edit shipping",
};

const dictionaries: Record<Lang, OrderLabels> = { ar, en };

/** Resolve per access, so a language switch is picked up on the next render. */
export const ot: OrderLabels = makeT(dictionaries);
