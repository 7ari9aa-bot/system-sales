import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../../../../core/constants/app_colors.dart';
import '../../../../core/printer/thermal_printer_manager.dart';
import '../../../../core/utils/money_formatter.dart';
import '../../../../core/zatca/zatca_qr_service.dart';
import '../../../../data/models/product.dart';

class ZatcaInvoiceDialog extends StatelessWidget {
  final String storeName;
  final String vatNumber;
  final String receiptNumber;
  final DateTime timestamp;
  final List<CartItem> items;
  final String subtotal;
  final String tax;
  final String total;
  final String paymentMethod;
  final String? cashierName;

  const ZatcaInvoiceDialog({
    super.key,
    required this.storeName,
    this.vatNumber = '300123456700003',
    required this.receiptNumber,
    required this.timestamp,
    required this.items,
    required this.subtotal,
    required this.tax,
    required this.total,
    required this.paymentMethod,
    this.cashierName,
  });

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final zatcaQr = ZatcaQrService.generateBase64Qr(
      sellerName: storeName,
      vatRegistrationNumber: vatNumber,
      timestamp: timestamp,
      invoiceTotalWithVat: total,
      vatTotal: tax,
    );

    return Dialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 460, maxHeight: 680),
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Header
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.all(8),
                        decoration: BoxDecoration(
                          color: AppColors.success.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: const Icon(Icons.verified, color: AppColors.success, size: 24),
                      ),
                      const SizedBox(width: 10),
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            'فاتورة ضريبية مبسطة',
                            style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                          ),
                          Text(
                            'متوافقة مع هيئة الزكاة والضريبة والجمارك (ZATCA)',
                            style: TextStyle(
                              fontSize: 11,
                              color: isDark ? Colors.grey[400] : Colors.grey[600],
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                  IconButton(
                    icon: const Icon(Icons.close),
                    onPressed: () => Navigator.pop(context),
                  ),
                ],
              ),
              const Divider(height: 20),

              // Content scrollable
              Expanded(
                child: SingleChildScrollView(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      // Store info
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: isDark
                              ? AppColors.surfaceDark
                              : Colors.grey.withValues(alpha: 0.06),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Column(
                          children: [
                            Text(
                              storeName,
                              style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              'الرقم الضريبي: $vatNumber',
                              style: const TextStyle(fontSize: 12),
                            ),
                            Text(
                              'رقم الفاتورة: $receiptNumber | التاريخ: ${_formatDate(timestamp)}',
                              style: TextStyle(
                                fontSize: 11,
                                color: isDark ? Colors.grey[400] : Colors.grey[600],
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 14),

                      // Items Table
                      const Text(
                        'الأصناف المباعة:',
                        style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
                      ),
                      const SizedBox(height: 6),
                      Container(
                        decoration: BoxDecoration(
                          border: Border.all(color: Colors.grey.withValues(alpha: 0.2)),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: ListView.separated(
                          shrinkWrap: true,
                          physics: const NeverScrollableScrollPhysics(),
                          itemCount: items.length,
                          separatorBuilder: (_, __) => const Divider(height: 1),
                          itemBuilder: (context, i) {
                            final item = items[i];
                            return Padding(
                              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                              child: Row(
                                children: [
                                  Expanded(
                                    child: Text(
                                      item.product.name,
                                      style: const TextStyle(fontSize: 13),
                                    ),
                                  ),
                                  Text(
                                    '${item.quantity} × ${MoneyFormatter.format(item.effectiveUnitPrice)}',
                                    style: const TextStyle(fontSize: 12, color: Colors.grey),
                                  ),
                                  const SizedBox(width: 12),
                                  Text(
                                    MoneyFormatter.format(item.lineTotal, currency: 'ر.س'),
                                    style: const TextStyle(
                                      fontSize: 13,
                                      fontWeight: FontWeight.bold,
                                    ),
                                  ),
                                ],
                              ),
                            );
                          },
                        ),
                      ),
                      const SizedBox(height: 14),

                      // Financial Breakdown
                      _buildSummaryRow('المجموع الخاضع للضريبة:', subtotal, currency: 'ر.س'),
                      const SizedBox(height: 4),
                      _buildSummaryRow('ضريبة القيمة المضافة (15%):', tax, currency: 'ر.س'),
                      const SizedBox(height: 4),
                      _buildSummaryRow(
                        'الإجمالي الكلي المستحق:',
                        total,
                        currency: 'ر.س',
                        isTotal: true,
                      ),
                      const SizedBox(height: 16),

                      // ZATCA Base64 TLV Box
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: AppColors.primary.withValues(alpha: 0.08),
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(
                            color: AppColors.primary.withValues(alpha: 0.3),
                          ),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                const Row(
                                  children: [
                                    Icon(Icons.qr_code_2, size: 20, color: AppColors.primary),
                                    SizedBox(width: 6),
                                    Text(
                                      'رمز الاستجابة السريعة (ZATCA TLV Base64)',
                                      style: TextStyle(
                                        fontSize: 12,
                                        fontWeight: FontWeight.bold,
                                        color: AppColors.primary,
                                      ),
                                    ),
                                  ],
                                ),
                                IconButton(
                                  icon: const Icon(Icons.copy, size: 16),
                                  tooltip: 'نسخ الرمز المشفر',
                                  onPressed: () {
                                    Clipboard.setData(ClipboardData(text: zatcaQr));
                                    ScaffoldMessenger.of(context).showSnackBar(
                                      const SnackBar(
                                        content: Text('تم نسخ رمز ZATCA إلى الحافظة بنجاح'),
                                        duration: Duration(seconds: 2),
                                      ),
                                    );
                                  },
                                ),
                              ],
                            ),
                            const SizedBox(height: 6),
                            SelectableText(
                              zatcaQr,
                              style: const TextStyle(
                                fontFamily: 'monospace',
                                fontSize: 10,
                                color: Colors.black87,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),

              const SizedBox(height: 12),
              // Footer Actions
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () => Navigator.pop(context),
                      child: const Text('إغلاق'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: OutlinedButton.icon(
                      icon: const Icon(Icons.share, size: 16),
                      label: const Text('واتساب / مشاركة'),
                      onPressed: () {
                        final text = _generateShareableText();
                        Clipboard.setData(ClipboardData(text: text));
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text('تم نسخ نص الفاتورة لمشاركتها عبر واتساب أو الرسائل'),
                            backgroundColor: AppColors.success,
                            duration: Duration(seconds: 3),
                          ),
                        );
                      },
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: ElevatedButton.icon(
                      icon: const Icon(Icons.print, size: 16),
                      label: const Text('طباعة'),
                      onPressed: () async {
                        final printerManager = context.read<ThermalPrinterManager>();
                        final ok = await printerManager.printReceipt(
                          storeName: storeName,
                          vatNumber: vatNumber,
                          receiptNumber: receiptNumber,
                          timestamp: timestamp,
                          items: items,
                          subtotal: subtotal,
                          tax: tax,
                          total: total,
                          paymentMethod: paymentMethod,
                          cashierName: cashierName,
                        );
                        if (context.mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(
                              content: Text(ok
                                  ? 'تم إرسال الفاتورة إلى الطابعة بنجاح'
                                  : (printerManager.lastError ?? 'فشل الاتصال بالطابعة')),
                              backgroundColor: ok ? AppColors.success : AppColors.error,
                            ),
                          );
                        }
                      },
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildSummaryRow(String label, String value,
      {required String currency, bool isTotal = false}) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(
          label,
          style: TextStyle(
            fontSize: isTotal ? 14 : 12,
            fontWeight: isTotal ? FontWeight.bold : FontWeight.normal,
          ),
        ),
        Text(
          MoneyFormatter.format(value, currency: currency),
          style: TextStyle(
            fontSize: isTotal ? 16 : 13,
            fontWeight: FontWeight.bold,
            color: isTotal ? AppColors.primary : null,
          ),
        ),
      ],
    );
  }

  String _formatDate(DateTime dt) {
    return '${dt.year}-${dt.month.toString().padLeft(2, '0')}-${dt.day.toString().padLeft(2, '0')} ${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  }

  String _generateShareableText() {
    final buffer = StringBuffer();
    buffer.writeln('🧾 *فاتورة ضريبية مبسطة*');
    buffer.writeln('🏬 المتجر: $storeName');
    buffer.writeln('🔢 الرقم الضريبي: $vatNumber');
    buffer.writeln('📄 رقم الفاتورة: $receiptNumber');
    buffer.writeln('📅 التاريخ: ${_formatDate(timestamp)}');
    buffer.writeln('--------------------------------');
    for (final item in items) {
      buffer.writeln('• ${item.product.name} × ${item.quantity} = ${MoneyFormatter.format(item.lineTotal, currency: 'ر.س')}');
    }
    buffer.writeln('--------------------------------');
    buffer.writeln('المجموع: ${MoneyFormatter.format(subtotal, currency: 'ر.س')}');
    buffer.writeln('الضريبة (15%): ${MoneyFormatter.format(tax, currency: 'ر.س')}');
    buffer.writeln('*الإجمالي النهائي: ${MoneyFormatter.format(total, currency: 'ر.س')}*');
    buffer.writeln('طريقة الدفع: $paymentMethod');
    buffer.writeln('✨ شكراً لتعاملكم معنا');
    return buffer.toString();
  }
}
