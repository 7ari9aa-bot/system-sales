/**
 * دمج قائمة الردود المعلقة بدل استبدالها.
 *
 * كل عملية مرتجع أو استبدال أو إلغاء بترجّع الردود اللي أنشأتها هي بس. لو الشاشة استبدلت القائمة
 * بالنتيجة الجديدة، رد بطاقة قديم لسه مستني الماكينة كان بيختفي من العرض مع إنه لسه معلق في قاعدة
 * البيانات — والكاشير يفتكر إن مفيش حاجة عليه.
 */
export function mergePendingRefunds(previous = [], incoming = []) {
  const byId = new Map();
  for (const row of previous ?? []) {
    if (row?.refund_id) byId.set(row.refund_id, row);
  }
  for (const row of incoming ?? []) {
    if (row?.refund_id) byId.set(row.refund_id, { ...byId.get(row.refund_id), ...row });
  }
  return [...byId.values()];
}

/** Remove one row once it is confirmed or rejected: it is no longer owed. */
export function withoutPendingRefund(rows = [], refundId) {
  return (rows ?? []).filter((row) => row.refund_id !== refundId);
}

/**
 * The list after the machine REFUSED a reversal.
 *
 * The refused row is gone (it is not pending any more), but the money is still owed: the answer
 * carries an ``outstanding`` row and it has to appear on the screen in the same update, or the
 * cashier closes the sale believing the customer was paid. Both the returns and the exchanges
 * screen use this, so the two can never drift.
 */
export function applyRejectedRefund(rows = [], result = {}) {
  const remaining = withoutPendingRefund(rows, result?.refund_id);
  return result?.outstanding ? mergePendingRefunds(remaining, [result.outstanding]) : remaining;
}
