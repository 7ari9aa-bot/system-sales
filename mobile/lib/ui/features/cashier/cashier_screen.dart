import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../core/constants/app_colors.dart';
import '../../../core/utils/money_formatter.dart';
import '../../../data/models/product.dart';
import '../../../l10n/generated/app_localizations.dart';
import '../../../providers/cashier_view_model.dart';
import 'widgets/camera_scanner_dialog.dart';
import 'widgets/cart_sheet.dart';

class CashierScreen extends StatefulWidget {
  const CashierScreen({super.key});

  @override
  State<CashierScreen> createState() => _CashierScreenState();
}

class _CashierScreenState extends State<CashierScreen> {
  final _searchController = TextEditingController();

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  void _openCart(BuildContext context) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => const CartSheet(),
    );
  }

  Future<void> _openCameraScanner(BuildContext context) async {
    final barcode = await showDialog<String>(
      context: context,
      builder: (_) => const CameraScannerDialog(),
    );

    if (barcode != null && barcode.isNotEmpty && context.mounted) {
      final cashierVm = context.read<CashierViewModel>();
      final found = await cashierVm.scanBarcode(barcode);
      if (!found && context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('لم يتم العثور على منتج بالباركود: $barcode'),
            backgroundColor: AppColors.warning,
          ),
        );
      }
    }
  }

  void _showBarcodeScannerDialog(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final cashierVm = context.read<CashierViewModel>();
    final barcodeController = TextEditingController();

    showDialog(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        title: Row(
          children: [
            const Icon(Icons.qr_code_scanner, color: AppColors.primary),
            const SizedBox(width: 8),
            Text(l10n.scanBarcode),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: barcodeController,
              autofocus: true,
              keyboardType: TextInputType.number,
              decoration: InputDecoration(
                hintText: '6281001001',
                suffixIcon: IconButton(
                  icon: const Icon(Icons.check),
                  onPressed: () async {
                    final code = barcodeController.text.trim();
                    if (code.isNotEmpty) {
                      Navigator.pop(dialogCtx);
                      final found = await cashierVm.scanBarcode(code);
                      if (!found && context.mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(
                            content: Text('${l10n.errorGeneric}: $code'),
                            backgroundColor: AppColors.warning,
                          ),
                        );
                      }
                    }
                  },
                ),
              ),
            ),
            const SizedBox(height: 16),
            const Text(
              'أو اختر باركود سريع للتجربة:',
              style: TextStyle(fontSize: 12, color: Colors.grey),
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: [
                ActionChip(
                  label: const Text('قهوة: 6281001001'),
                  onPressed: () async {
                    Navigator.pop(dialogCtx);
                    await cashierVm.scanBarcode('6281001001');
                  },
                ),
                ActionChip(
                  label: const Text('تمر: 6281001002'),
                  onPressed: () async {
                    Navigator.pop(dialogCtx);
                    await cashierVm.scanBarcode('6281001002');
                  },
                ),
              ],
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogCtx),
            child: Text(l10n.cancel),
          ),
        ],
      ),
    );
  }

  void _showHeldCartsDialog(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final cashierVm = context.read<CashierViewModel>();

    showDialog(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        title: Text(l10n.holdCart),
        content: SizedBox(
          width: double.maxFinite,
          child: cashierVm.heldCarts.isEmpty
              ? const Center(child: Text('لا توجد فواتير معلقة'))
              : ListView.separated(
                  shrinkWrap: true,
                  itemCount: cashierVm.heldCarts.length,
                  separatorBuilder: (_, __) => const Divider(),
                  itemBuilder: (ctx, index) {
                    final held = cashierVm.heldCarts[index];
                    final count = held.fold(0, (sum, i) => sum + i.quantity);
                    return ListTile(
                      leading: const CircleAvatar(
                        child: Icon(Icons.receipt_long),
                      ),
                      title: Text('فاتورة معلقة #${index + 1}'),
                      subtitle: Text('$count عناصر'),
                      trailing: ElevatedButton(
                        child: const Text('استرجاع'),
                        onPressed: () {
                          cashierVm.resumeHeldCart(index);
                          Navigator.pop(dialogCtx);
                          _openCart(context);
                        },
                      ),
                    );
                  },
                ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogCtx),
            child: Text(l10n.cancel),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final cashierVm = context.watch<CashierViewModel>();
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.cashierTitle),
        actions: [
          if (cashierVm.heldCarts.isNotEmpty)
            Stack(
              alignment: Alignment.center,
              children: [
                IconButton(
                  icon: const Icon(Icons.pause_circle_outline),
                  tooltip: 'الفواتير المعلقة',
                  onPressed: () => _showHeldCartsDialog(context),
                ),
                Positioned(
                  top: 8,
                  right: 8,
                  child: Container(
                    padding: const EdgeInsets.all(4),
                    decoration: const BoxDecoration(
                      color: AppColors.warning,
                      shape: BoxShape.circle,
                    ),
                    child: Text(
                      '${cashierVm.heldCarts.length}',
                      style: const TextStyle(
                        fontSize: 10,
                        fontWeight: FontWeight.bold,
                        color: Colors.white,
                      ),
                    ),
                  ),
                ),
              ],
            ),
          IconButton(
            icon: const Icon(Icons.qr_code),
            tooltip: 'إدخال باركود يدوي',
            onPressed: () => _showBarcodeScannerDialog(context),
          ),
          IconButton(
            icon: const Icon(Icons.qr_code_scanner),
            tooltip: 'مسح بالكاميرا',
            onPressed: () => _openCameraScanner(context),
          ),
        ],
      ),
      body: Column(
        children: [
          if (cashierVm.pendingOfflineCount > 0)
            Container(
              color: AppColors.warning.withValues(alpha: 0.15),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                children: [
                  const Icon(Icons.cloud_off, color: AppColors.warning, size: 20),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'يوجد ${cashierVm.pendingOfflineCount} مبيعات بانتظار المزامنة',
                      style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13),
                    ),
                  ),
                  TextButton(
                    onPressed: () async {
                      final count = await cashierVm.syncOfflineSales();
                      if (context.mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(content: Text('تمت مزامنة $count مبيعات بنجاح')),
                        );
                      }
                    },
                    child: const Text('مزامنة الآن'),
                  ),
                ],
              ),
            ),

          // Search & Filter Bar
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _searchController,
                    decoration: InputDecoration(
                      hintText: l10n.searchProductHint,
                      prefixIcon: const Icon(Icons.search),
                      suffixIcon: _searchController.text.isNotEmpty
                          ? IconButton(
                              icon: const Icon(Icons.clear),
                              onPressed: () {
                                _searchController.clear();
                                cashierVm.searchProducts('');
                              },
                            )
                          : null,
                    ),
                    onChanged: (val) => cashierVm.searchProducts(val),
                  ),
                ),
                const SizedBox(width: 8),
                Container(
                  height: 48,
                  width: 48,
                  decoration: BoxDecoration(
                    color: AppColors.primary,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: IconButton(
                    icon: const Icon(Icons.qr_code_scanner, color: Colors.white),
                    tooltip: l10n.scanBarcode,
                    onPressed: () => _openCameraScanner(context),
                  ),
                ),
              ],
            ),
          ),

          // Product Catalog Grid
          Expanded(
            child: cashierVm.isLoading
                ? const Center(child: CircularProgressIndicator())
                : cashierVm.products.isEmpty
                    ? Center(
                        child: Text(
                          'لا توجد منتجات مطابقة',
                          style: TextStyle(
                            color: isDark ? Colors.grey[400] : Colors.grey[600],
                          ),
                        ),
                      )
                    : GridView.builder(
                        padding: const EdgeInsets.fromLTRB(16, 8, 16, 88),
                        gridDelegate:
                            const SliverGridDelegateWithFixedCrossAxisCount(
                          crossAxisCount: 2,
                          crossAxisSpacing: 12,
                          mainAxisSpacing: 12,
                          childAspectRatio: 0.88,
                        ),
                        itemCount: cashierVm.products.length,
                        itemBuilder: (context, index) {
                          final product = cashierVm.products[index];
                          return _buildProductCard(context, product, isDark);
                        },
                      ),
          ),
        ],
      ),

      // Sticky Bottom Cart Bar
      bottomSheet: cashierVm.cartCount > 0
          ? Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              decoration: BoxDecoration(
                color: isDark ? AppColors.surfaceDark : Colors.white,
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.08),
                    blurRadius: 10,
                    offset: const Offset(0, -4),
                  ),
                ],
              ),
              child: SafeArea(
                child: Row(
                  children: [
                    // Badge & Count
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 8,
                      ),
                      decoration: BoxDecoration(
                        color: AppColors.primary.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Row(
                        children: [
                          const Icon(
                            Icons.shopping_cart,
                            color: AppColors.primary,
                            size: 20,
                          ),
                          const SizedBox(width: 6),
                          Text(
                            '${cashierVm.cartCount}',
                            style: const TextStyle(
                              color: AppColors.primary,
                              fontWeight: FontWeight.bold,
                              fontSize: 16,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(width: 12),

                    // Total display & open button
                    Expanded(
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 16,
                            vertical: 12,
                          ),
                        ),
                        onPressed: () => _openCart(context),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text(l10n.cartTitle),
                            Text(
                              MoneyFormatter.format(
                                cashierVm.total,
                                currency: l10n.currencySar,
                              ),
                              style: const TextStyle(
                                fontWeight: FontWeight.bold,
                                fontSize: 16,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            )
          : null,
    );
  }

  Widget _buildProductCard(BuildContext context, Product product, bool isDark) {
    final l10n = AppLocalizations.of(context)!;
    final cashierVm = context.read<CashierViewModel>();

    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () => cashierVm.addToCart(product),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Category badge & stock
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: AppColors.primary.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      product.category ?? 'عام',
                      style: const TextStyle(
                        color: AppColors.primary,
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  Text(
                    'مخزون: ${product.stockQuantity}',
                    style: TextStyle(
                      fontSize: 11,
                      color: product.stockQuantity < 15
                          ? AppColors.warning
                          : (isDark ? Colors.grey[400] : Colors.grey[600]),
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ],
              ),
              const Spacer(),

              // Product Name
              Text(
                product.name,
                style: const TextStyle(
                  fontWeight: FontWeight.bold,
                  fontSize: 14,
                ),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
              const SizedBox(height: 6),

              // Barcode display if exists
              if (product.barcode != null)
                Text(
                  product.barcode!,
                  style: TextStyle(
                    fontSize: 11,
                    color: isDark ? Colors.grey[500] : Colors.grey[600],
                  ),
                ),
              const Spacer(),

              // Price & Add Button Row
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    MoneyFormatter.format(
                      product.price,
                      currency: l10n.currencySar,
                    ),
                    style: const TextStyle(
                      fontWeight: FontWeight.bold,
                      fontSize: 15,
                      color: AppColors.primary,
                    ),
                  ),
                  Container(
                    width: 36,
                    height: 36,
                    decoration: BoxDecoration(
                      color: AppColors.primary,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: const Icon(
                      Icons.add,
                      color: Colors.white,
                      size: 20,
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
}
