import { withApproval } from "./posApi";

/** The server says "a manager must approve this" with a stable code (not by its wording). */
export function needsApproval(error) {
  return error?.code === "approval_required";
}

const LIMIT_TEXT = {
  refund: "المرتجع أكبر من الحد المسموح للكاشير",
  cash_out: "المبلغ المسحوب من الدرج أكبر من الحد المسموح للكاشير",
  discount: "الخصم أكبر من الحد المسموح للكاشير",
};

/** One sentence for the dialog: which limit, and how much. Falls back to the server's own words. */
export function approvalReason(error) {
  const limit = error?.details?.limit;
  const ceiling = error?.details?.ceiling;
  const head = LIMIT_TEXT[limit] ?? error?.message ?? "هذه العملية تحتاج موافقة مدير";
  if (ceiling == null) return head;
  return limit === "discount" ? `${head} (${ceiling}%)` : `${head} (${ceiling})`;
}

/** A PIN is 4 to 8 ASCII digits, the same rule the server enforces. */
export function pinProblem(pin) {
  if (!pin) return "اكتب رقم PIN المدير";
  if (!/^[0-9]{4,8}$/.test(pin)) return "رقم PIN من 4 إلى 8 أرقام إنجليزية";
  return null;
}

/**
 * Run one money call. If the server asks for a manager, return `{ needsApproval, error }` so the
 * screen can open the dialog; the retry is `run(call, approval)` with the SAME intent, so the
 * Idempotency-Key does not change and the manager's OK is part of the same tap, not a second one.
 */
export async function runWithApproval(call, intent, approval) {
  try {
    const data = await call(approval ? withApproval(intent, approval) : intent);
    return { ok: true, data };
  } catch (error) {
    if (needsApproval(error) && !approval) return { ok: false, needsApproval: true, error };
    throw error;
  }
}

/**
 * What to tell the cashier when the manager's OK was not accepted. The server answers every
 * refusal (wrong PIN, no such manager, locked out, not a manager) with one 403 on purpose, so the
 * till does not say which: it only says to check and retry.
 */
export function approvalFailure(error) {
  if (error?.status === 403) return "تعذّر اعتماد المدير. تأكد من اختيار المدير ومن رقم PIN ثم حاول مرة أخرى.";
  if (error?.status === 429) return "محاولات كثيرة. انتظر قليلًا ثم حاول مرة أخرى.";
  return error?.message || "تعذّر إتمام العملية.";
}
