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
