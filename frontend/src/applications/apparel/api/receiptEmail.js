/**
 * "Email me this receipt": the address check before any request, and the Arabic text for a refusal.
 *
 * One address only: the server refuses a list or a header-injection string, so the screen refuses
 * it first. The server's own wording is English and technical; the cashier reads a plain Arabic
 * sentence for the cause that matters to them.
 */
const ONE_ADDRESS = /^[^\s@,;<>()[\]\\"]+@[^\s@,;<>()[\]\\"]+\.[^\s@,;<>()[\]\\".]{2,}$/;

export const validReceiptEmail = (value) => {
  const v = String(value ?? "").trim();
  return v.length <= 254 && ONE_ADDRESS.test(v);
};

export function receiptEmailProblem(err) {
  const text = String(err?.message ?? "").toLowerCase();
  if (text.includes("not configured")) return "إرسال الإيميل غير مفعّل على هذا النظام. اطلب من المسؤول تفعيله.";
  if (err?.status === 429 || err?.code === "rate_limit_exceeded") return "الإيصال ده اتبعت لإيميلات كتير النهارده. جرّب بكرة.";
  return "تعذّر إرسال الإيصال بالإيميل. راجع العنوان وجرّب تاني.";
}

/**
 * Ask the server to email the receipt and say, in Arabic, what happened. One call, never thrown:
 * the dialog shows `message` and decides the colour from `ok`.
 */
export async function submitReceiptEmail(send, receiptId, email) {
  if (!receiptId) return { ok: false, message: "لم يُسجَّل الإيصال بعد. أعد المحاولة بعد حفظه." };
  if (!validReceiptEmail(email)) return { ok: false, message: "اكتب عنوان إيميل واحد صحيح." };
  try {
    await send(receiptId, String(email).trim());
    return { ok: true, message: "اتبعت الإيصال للإيميل." };
  } catch (err) {
    return { ok: false, message: receiptEmailProblem(err) };
  }
}
