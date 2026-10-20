import { PAYMENT_METHODS } from "@/cashier/lib/format";

// تحويل فاتورة مسجلة إلى كائن معاينة الفاتورة الحرارية.
export function invoiceToReceipt(invoice) {
  return {
    number: invoice.number,
    date: invoice.date,
    cashier: invoice.cashier,
    customerName: invoice.customerName,
    items: invoice.items.map((it) => ({ ...it, total: +(it.price * it.qty - it.discount).toFixed(2) })),
    pieces: invoice.pieces,
    subTotal: invoice.subTotal,
    discount: invoice.discount,
    total: invoice.total,
    paid: invoice.paid,
    payment: invoice.payment,
    paymentLabel: PAYMENT_METHODS[invoice.payment].label,
    status: invoice.status,
  };
}