import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../../core/constants/app_colors.dart';
import '../../../../core/printer/thermal_printer_manager.dart';
import '../../../../core/utils/money_formatter.dart';
import '../../../../l10n/generated/app_localizations.dart';
import '../../../../providers/cashier_view_model.dart';
import '../../../../providers/auth_view_model.dart';
import 'zatca_invoice_dialog.dart';

class CartSheet extends StatelessWidget {
  const CartSheet({super.key});

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final cashierVm = context.watch<CashierViewModel>();
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Container(
      decoration: BoxDecoration(
        color: isDark ? AppColors.surfaceDark : Colors.white,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
      ),
      padding: EdgeInsets.only(
        left: 16,
        right: 16,
        top: 12,
        bottom: MediaQuery.of(context).viewInsets.bottom + 16,
      ),
      child: SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Handle bar
            Center(
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: Colors.grey.withValues(alpha: 0.4),
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            const SizedBox(height: 12),

            // Header
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Row(
                  children: [
                    const Icon(Icons.shopping_cart_outlined, color: AppColors.primary),
                    const SizedBox(width: 8),
                    Text(
                      l10n.cartTitle,
                      style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: AppColors.primary.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(
                        '${cashierVm.cartCount}',
                        style: const TextStyle(
                          color: AppColors.primary,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ],
                ),
                if (cashierVm.cartItems.isNotEmpty)
                  TextButton.icon(
                    onPressed: () => cashierVm.clearCart(),
                    icon: const Icon(Icons.delete_outline, size: 18, color: AppColors.error),
                    label: Text(
                      l10n.cancel,
                      style: const TextStyle(color: AppColors.error),
                    ),
                  ),
              ],
            ),
            const Divider(height: 20),

            // Cart Items List
            if (cashierVm.cartItems.isEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 32),
                child: Column(
                  children: [
                    Icon(
                      Icons.remove_shopping_cart_outlined,
                      size: 48,
                      color: isDark ? Colors.grey[600] : Colors.grey[400],
                    ),
                    const SizedBox(height: 12),
                    Text(
                      l10n.emptyCart,
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        color: isDark ? Colors.grey[400] : Colors.grey[600],
                      ),
                    ),
                  ],
                ),
              )
            else
              ConstrainedBox(
                constraints: BoxConstraints(
                  maxHeight: MediaQuery.of(context).size.height * 0.38,
                ),
                child: ListView.separated(
                  shrinkWrap: true,
                  itemCount: cashierVm.cartItems.length,
                  separatorBuilder: (_, __) => const Divider(height: 1),
                  itemBuilder: (context, index) {
                    final item = cashierVm.cartItems[index];
                    return Padding(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      child: Row(
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  item.product.name,
                                  style: const TextStyle(fontWeight: FontWeight.w600),
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  MoneyFormatter.format(
                                    item.effectiveUnitPrice,
                                    currency: l10n.currencySar,
                                  ),
                                  style: TextStyle(
                                    fontSize: 12,
                                    color: isDark
                                        ? AppColors.textSecondaryDark
                                        : AppColors.textSecondaryLight,
                                  ),
                                ),
                              ],
                            ),
                          ),

                          // Quantity Controls
                          Container(
                            decoration: BoxDecoration(
                              color: isDark
                                  ? AppColors.backgroundDark
                                  : AppColors.backgroundLight,
                              borderRadius: BorderRadius.circular(8),
                              border: Border.all(
                                color: isDark
                                    ? AppColors.borderDark
                                    : AppColors.borderLight,
                              ),
                            ),
                            child: Row(
                              children: [
                                IconButton(
                                  icon: const Icon(Icons.remove, size: 16),
                                  constraints: const BoxConstraints(
                                    minWidth: 32,
                                    minHeight: 32,
                                  ),
                                  padding: EdgeInsets.zero,
                                  onPressed: () =>
                                      cashierVm.updateQuantity(item.product, -1),
                                ),
                                Padding(
                                  padding: const EdgeInsets.symmetric(horizontal: 8),
                                  child: Text(
                                    '${item.quantity}',
                                    style: const TextStyle(fontWeight: FontWeight.bold),
                                  ),
                                ),
                                IconButton(
                                  icon: const Icon(Icons.add, size: 16),
                                  constraints: const BoxConstraints(
                                    minWidth: 32,
                                    minHeight: 32,
                                  ),
                                  padding: EdgeInsets.zero,
                                  onPressed: () =>
                                      cashierVm.updateQuantity(item.product, 1),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(width: 12),

                          // Line Total
                          SizedBox(
                            width: 72,
                            child: Text(
                              MoneyFormatter.format(
                                item.lineTotal,
                                currency: l10n.currencySar,
                              ),
                              textAlign: TextAlign.end,
                              style: const TextStyle(
                                fontWeight: FontWeight.bold,
                                fontSize: 13,
                              ),
                            ),
                          ),
                        ],
                      ),
                    );
                  },
                ),
              ),

            if (cashierVm.cartItems.isNotEmpty) ...[
              const Divider(height: 24),

              // Price Breakdown
              _buildPriceRow(l10n.subtotal, cashierVm.subtotal, l10n.currencySar),
              const SizedBox(height: 4),
              _buildPriceRow(l10n.tax, cashierVm.tax, l10n.currencySar),
              const SizedBox(height: 8),
              _buildPriceRow(
                l10n.total,
                cashierVm.total,
                l10n.currencySar,
                isTotal: true,
              ),
              const SizedBox(height: 16),

              // Action Buttons: Hold and Checkout
              Row(
                children: [
                  OutlinedButton.icon(
                    onPressed: () {
                      cashierVm.holdCurrentCart();
                      Navigator.pop(context);
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(content: Text(l10n.cartHeldSuccess)),
                      );
                    },
                    icon: const Icon(Icons.pause, size: 18),
                    label: Text(l10n.holdCart),
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: ElevatedButton.icon(
                      onPressed: () => _showPaymentDialog(context),
                      icon: const Icon(Icons.check_circle_outline, size: 20),
                      label: Text(l10n.checkout),
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildPriceRow(String label, String value, String currency, {bool isTotal = false}) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(
          label,
          style: TextStyle(
            fontSize: isTotal ? 16 : 13,
            fontWeight: isTotal ? FontWeight.bold : FontWeight.normal,
          ),
        ),
        Text(
          MoneyFormatter.format(value, currency: currency),
          style: TextStyle(
            fontSize: isTotal ? 18 : 13,
            fontWeight: isTotal ? FontWeight.bold : FontWeight.w600,
            color: isTotal ? AppColors.primary : null,
          ),
        ),
      ],
    );
  }

  void _showPaymentDialog(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final cashierVm = context.read<CashierViewModel>();

    showDialog(
      context: context,
      builder: (dialogCtx) {
        return AlertDialog(
          title: Text(l10n.checkout),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                '${l10n.total}: ${MoneyFormatter.format(cashierVm.total, currency: l10n.currencySar)}',
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 20),
              ElevatedButton.icon(
                icon: const Icon(Icons.payments_outlined),
                label: Text(l10n.payCash),
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.primary,
                ),
                onPressed: () async {
                  Navigator.pop(dialogCtx);
                  final success = await cashierVm.checkout(paymentMethod: 'cash');
                  if (context.mounted && success) {
                    Navigator.pop(context); // close cart sheet
                    _showSuccessDialog(context, cashierVm.lastReceiptNumber);
                  }
                },
              ),
              const SizedBox(height: 12),
              ElevatedButton.icon(
                icon: const Icon(Icons.credit_card_outlined),
                label: Text(l10n.payCard),
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.secondary,
                ),
                onPressed: () async {
                  Navigator.pop(dialogCtx);
                  final success = await cashierVm.checkout(paymentMethod: 'card');
                  if (context.mounted && success) {
                    Navigator.pop(context); // close cart sheet
                    _showSuccessDialog(context, cashierVm.lastReceiptNumber);
                  }
                },
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogCtx),
              child: Text(l10n.cancel),
            ),
          ],
        );
      },
    );
  }

  void _showSuccessDialog(BuildContext context, String? receiptNumber) {
    final l10n = AppLocalizations.of(context)!;
    final cashierVm = context.read<CashierViewModel>();
    final authVm = context.read<AuthViewModel>();
    final isOffline = cashierVm.isLastSaleOffline;

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        icon: Icon(
          isOffline ? Icons.cloud_off : Icons.check_circle,
          color: isOffline ? AppColors.warning : AppColors.success,
          size: 54,
        ),
        title: Text(isOffline ? 'تم الحفظ في وضع عدم الاتصال' : l10n.saleCompletedSuccess),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              '${l10n.receiptNumber}: ${receiptNumber ?? "REC-1001"}',
              textAlign: TextAlign.center,
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
            if (isOffline) ...[
              const SizedBox(height: 8),
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: AppColors.warning.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Text(
                  'تم حفظ الفاتورة محلياً بأمان، وسيتم مزامنتها تلقائياً مع السحابة فور توفر الاتصال.',
                  style: TextStyle(fontSize: 12),
                  textAlign: TextAlign.center,
                ),
              ),
            ],
            const SizedBox(height: 16),
            ElevatedButton.icon(
              icon: const Icon(Icons.print),
              label: const Text('طباعة الفاتورة فوراً'),
              onPressed: () async {
                final printerManager = context.read<ThermalPrinterManager>();
                final ok = await printerManager.printReceipt(
                  storeName: authVm.currentUser?.tenantName ?? 'متجر فهرست',
                  vatNumber: '300123456700003',
                  receiptNumber: receiptNumber ?? 'REC-1001',
                  timestamp: DateTime.now(),
                  items: cashierVm.lastCompletedItems,
                  subtotal: cashierVm.subtotal,
                  tax: cashierVm.tax,
                  total: cashierVm.total,
                  paymentMethod: 'cash',
                  cashierName: authVm.currentUser?.name,
                );
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text(ok
                          ? 'تم إرسال أمر الطباعة إلى الطابعة'
                          : (printerManager.lastError ?? 'تعذر الاتصال بالطابعة')),
                      backgroundColor: ok ? AppColors.success : AppColors.error,
                    ),
                  );
                }
              },
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              icon: const Icon(Icons.receipt_long_outlined),
              label: const Text('معاينة الفاتورة الضريبية (ZATCA)'),
              onPressed: () {
                showDialog(
                  context: ctx,
                  builder: (_) => ZatcaInvoiceDialog(
                    storeName: authVm.currentUser?.tenantName ?? 'متجر فهرست',
                    vatNumber: '300123456700003',
                    receiptNumber: receiptNumber ?? 'REC-1001',
                    timestamp: DateTime.now(),
                    items: cashierVm.lastCompletedItems,
                    subtotal: cashierVm.subtotal,
                    tax: cashierVm.tax,
                    total: cashierVm.total,
                    paymentMethod: 'cash',
                    cashierName: authVm.currentUser?.name,
                  ),
                );
              },
            ),
          ],
        ),
        actions: [
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('تم'),
          ),
        ],
      ),
    );
  }
}
