import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../core/constants/app_colors.dart';
import '../../../data/models/product.dart';
import '../../../l10n/generated/app_localizations.dart';
import '../../../providers/inventory_view_model.dart';
import '../cashier/widgets/camera_scanner_dialog.dart';
import 'widgets/continuous_stocktake_dialog.dart';

class InventoryScreen extends StatefulWidget {
  const InventoryScreen({super.key});

  @override
  State<InventoryScreen> createState() => _InventoryScreenState();
}

class _InventoryScreenState extends State<InventoryScreen> {
  final TextEditingController _searchController = TextEditingController();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<InventoryViewModel>().loadInventory();
    });
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _openCameraScanner() async {
    final scannedCode = await showDialog<String>(
      context: context,
      builder: (_) => const CameraScannerDialog(),
    );

    if (scannedCode != null && mounted) {
      _searchController.text = scannedCode;
      context.read<InventoryViewModel>().setSearchQuery(scannedCode);
    }
  }

  void _showAdjustDialog(BuildContext context, Product product) {
    final l10n = AppLocalizations.of(context)!;
    String direction = 'in';
    int delta = 1;
    String reason = 'adjustment';
    final controller = TextEditingController(text: '1');

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheetState) {
          final isDark = Theme.of(ctx).brightness == Brightness.dark;
          final previewStock = direction == 'in'
              ? product.stockQuantity + delta
              : (product.stockQuantity - delta).clamp(0, 999999);

          return Padding(
            padding: EdgeInsets.only(
              left: 20,
              right: 20,
              top: 20,
              bottom: MediaQuery.of(ctx).viewInsets.bottom + 24,
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.all(8),
                      decoration: BoxDecoration(
                        color: AppColors.primary.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: const Icon(Icons.tune, color: AppColors.primary),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            l10n.adjustStock,
                            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                          ),
                          Text(
                            product.name,
                            style: TextStyle(
                              fontSize: 13,
                              color: isDark ? Colors.grey[400] : Colors.grey[600],
                            ),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.close),
                      onPressed: () => Navigator.pop(ctx),
                    ),
                  ],
                ),
                const Divider(height: 24),

                // Direction selector
                Row(
                  children: [
                    Expanded(
                      child: ChoiceChip(
                        label: const Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(Icons.add, size: 16),
                            SizedBox(width: 4),
                            Text('إضافة (وارد)'),
                          ],
                        ),
                        selected: direction == 'in',
                        onSelected: (val) {
                          if (val) setSheetState(() => direction = 'in');
                        },
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: ChoiceChip(
                        label: const Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(Icons.remove, size: 16),
                            SizedBox(width: 4),
                            Text('خصم (عجز / تالف)'),
                          ],
                        ),
                        selected: direction == 'out',
                        onSelected: (val) {
                          if (val) setSheetState(() => direction = 'out');
                        },
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),

                // Quantity Input
                Row(
                  children: [
                    IconButton(
                      icon: const Icon(Icons.remove_circle_outline),
                      onPressed: () {
                        if (delta > 1) {
                          setSheetState(() {
                            delta--;
                            controller.text = '$delta';
                          });
                        }
                      },
                    ),
                    Expanded(
                      child: TextField(
                        controller: controller,
                        keyboardType: TextInputType.number,
                        textAlign: TextAlign.center,
                        decoration: const InputDecoration(
                          labelText: 'الكمية',
                          border: OutlineInputBorder(),
                        ),
                        onChanged: (val) {
                          final parsed = int.tryParse(val) ?? 1;
                          setSheetState(() {
                            delta = parsed > 0 ? parsed : 1;
                          });
                        },
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.add_circle_outline),
                      onPressed: () {
                        setSheetState(() {
                          delta++;
                          controller.text = '$delta';
                        });
                      },
                    ),
                  ],
                ),
                const SizedBox(height: 16),

                // Reason dropdown
                DropdownButtonFormField<String>(
                  value: reason,
                  decoration: InputDecoration(
                    labelText: l10n.reason,
                    border: const OutlineInputBorder(),
                  ),
                  items: [
                    DropdownMenuItem(value: 'adjustment', child: Text(l10n.reasonAdjustment)),
                    DropdownMenuItem(value: 'damage', child: Text(l10n.reasonDamage)),
                    DropdownMenuItem(value: 'deficit', child: Text(l10n.reasonDeficit)),
                    DropdownMenuItem(value: 'stocktake', child: Text(l10n.reasonStocktake)),
                  ],
                  onChanged: (val) {
                    if (val != null) setSheetState(() => reason = val);
                  },
                ),
                const SizedBox(height: 16),

                // Balance preview
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                  decoration: BoxDecoration(
                    color: isDark ? Colors.grey[850] : Colors.grey[100],
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text('${l10n.currentStock}: ${product.stockQuantity}'),
                      const Icon(Icons.arrow_forward, size: 16),
                      Text(
                        '${l10n.newStock}: $previewStock',
                        style: const TextStyle(fontWeight: FontWeight.bold, color: AppColors.primary),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 20),

                // Submit button
                ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.primary,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                  ),
                  onPressed: () async {
                    Navigator.pop(ctx);
                    final vm = context.read<InventoryViewModel>();
                    final ok = await vm.adjustStock(
                      product: product,
                      deltaQuantity: delta,
                      direction: direction,
                      reason: reason,
                    );
                    if (context.mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(
                          content: Text(ok ? l10n.adjustmentSuccess : l10n.errorGeneric),
                          duration: const Duration(seconds: 2),
                        ),
                      );
                    }
                  },
                  child: Text(l10n.confirmAdjustment),
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  void _showCountDialog(BuildContext context, Product product) {
    final l10n = AppLocalizations.of(context)!;
    int counted = product.stockQuantity;
    final controller = TextEditingController(text: '$counted');

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheetState) {
          final isDark = Theme.of(ctx).brightness == Brightness.dark;
          final diff = counted - product.stockQuantity;

          return Padding(
            padding: EdgeInsets.only(
              left: 20,
              right: 20,
              top: 20,
              bottom: MediaQuery.of(ctx).viewInsets.bottom + 24,
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.all(8),
                      decoration: BoxDecoration(
                        color: AppColors.secondary.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: const Icon(Icons.fact_check, color: AppColors.secondary),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            l10n.stockCount,
                            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                          ),
                          Text(
                            product.name,
                            style: TextStyle(
                              fontSize: 13,
                              color: isDark ? Colors.grey[400] : Colors.grey[600],
                            ),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.close),
                      onPressed: () => Navigator.pop(ctx),
                    ),
                  ],
                ),
                const Divider(height: 24),

                Text(
                  '${l10n.currentStock}: ${product.stockQuantity} وحدة',
                  style: TextStyle(
                    fontSize: 14,
                    color: isDark ? Colors.grey[300] : Colors.grey[700],
                  ),
                ),
                const SizedBox(height: 12),

                // Actual Count Input
                TextField(
                  controller: controller,
                  keyboardType: TextInputType.number,
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
                  decoration: InputDecoration(
                    labelText: l10n.newStock,
                    border: const OutlineInputBorder(),
                  ),
                  onChanged: (val) {
                    final parsed = int.tryParse(val) ?? 0;
                    setSheetState(() {
                      counted = parsed >= 0 ? parsed : 0;
                    });
                  },
                ),
                const SizedBox(height: 16),

                // Variance Indicator
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                  decoration: BoxDecoration(
                    color: diff == 0
                        ? (isDark ? Colors.grey[850] : Colors.grey[100])
                        : (diff > 0
                            ? Colors.green.withValues(alpha: 0.15)
                            : Colors.red.withValues(alpha: 0.15)),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text('الفارق (Variance):'),
                      Text(
                        diff == 0
                            ? 'مطابق تماماً'
                            : (diff > 0 ? '+$diff وحدة (فائض)' : '$diff وحدة (عجز)'),
                        style: TextStyle(
                          fontWeight: FontWeight.bold,
                          color: diff == 0
                              ? Colors.grey[600]
                              : (diff > 0 ? Colors.green : Colors.red),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 20),

                // Submit button
                ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.secondary,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                  ),
                  onPressed: () async {
                    Navigator.pop(ctx);
                    final vm = context.read<InventoryViewModel>();
                    final ok = await vm.countStock(
                      product: product,
                      countedQuantity: counted,
                    );
                    if (context.mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(
                          content: Text(ok ? l10n.adjustmentSuccess : l10n.errorGeneric),
                          duration: const Duration(seconds: 2),
                        ),
                      );
                    }
                  },
                  child: Text(l10n.confirmAdjustment),
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  void _showAddProductDialog(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final nameCtrl = TextEditingController();
    final priceCtrl = TextEditingController();
    final barcodeCtrl = TextEditingController();
    final categoryCtrl = TextEditingController(text: 'عام');
    final stockCtrl = TextEditingController(text: '10');

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheetState) {
          return Padding(
            padding: EdgeInsets.only(
              left: 20,
              right: 20,
              top: 20,
              bottom: MediaQuery.of(ctx).viewInsets.bottom + 24,
            ),
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.all(8),
                        decoration: BoxDecoration(
                          color: AppColors.primary.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: const Icon(Icons.add_box_outlined, color: AppColors.primary),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          l10n.addProduct,
                          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.close),
                        onPressed: () => Navigator.pop(ctx),
                      ),
                    ],
                  ),
                  const Divider(height: 20),

                  // Product Name
                  TextField(
                    controller: nameCtrl,
                    decoration: InputDecoration(
                      labelText: l10n.productName,
                      prefixIcon: const Icon(Icons.label_outline),
                    ),
                  ),
                  const SizedBox(height: 12),

                  // Price
                  TextField(
                    controller: priceCtrl,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: InputDecoration(
                      labelText: l10n.price,
                      suffixText: 'ر.س',
                      prefixIcon: const Icon(Icons.payments_outlined),
                    ),
                  ),
                  const SizedBox(height: 12),

                  // Barcode with Camera Scan button
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: barcodeCtrl,
                          decoration: const InputDecoration(
                            labelText: 'الباركود / الكود',
                            prefixIcon: Icon(Icons.qr_code),
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      IconButton.filledTonal(
                        icon: const Icon(Icons.camera_alt),
                        tooltip: 'مسح بالكاميرا',
                        onPressed: () async {
                          final code = await showDialog<String>(
                            context: ctx,
                            builder: (_) => const CameraScannerDialog(),
                          );
                          if (code != null && code.isNotEmpty) {
                            setSheetState(() {
                              barcodeCtrl.text = code;
                            });
                          }
                        },
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),

                  // Category & Initial Stock
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: categoryCtrl,
                          decoration: InputDecoration(
                            labelText: l10n.category,
                            prefixIcon: const Icon(Icons.category_outlined),
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: TextField(
                          controller: stockCtrl,
                          keyboardType: TextInputType.number,
                          decoration: InputDecoration(
                            labelText: l10n.initialStock,
                            prefixIcon: const Icon(Icons.inventory_2_outlined),
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 20),

                  // Submit button
                  ElevatedButton(
                    style: ElevatedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 14),
                    ),
                    onPressed: () async {
                      final name = nameCtrl.text.trim();
                      final price = priceCtrl.text.trim();
                      if (name.isEmpty || price.isEmpty) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text('يرجى إدخال اسم المنتج والسعر على الأقل'),
                            backgroundColor: AppColors.error,
                          ),
                        );
                        return;
                      }

                      final stock = int.tryParse(stockCtrl.text.trim()) ?? 0;
                      Navigator.pop(ctx);

                      final created = await context.read<InventoryViewModel>().createProduct(
                            name: name,
                            price: price,
                            barcode: barcodeCtrl.text.trim().isNotEmpty ? barcodeCtrl.text.trim() : null,
                            category: categoryCtrl.text.trim(),
                            initialStock: stock,
                          );

                      if (context.mounted && created != null) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(
                            content: Text('${l10n.productAddedSuccess}: ${created.name}'),
                            backgroundColor: AppColors.success,
                          ),
                        );
                      }
                    },
                    child: Text(l10n.save),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final invVm = context.watch<InventoryViewModel>();
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.inventoryTitle),
        actions: [
          IconButton(
            icon: const Icon(Icons.document_scanner_outlined),
            tooltip: 'الجرد المتتابع بالماسح',
            onPressed: () async {
              final count = await Navigator.push<int>(
                context,
                MaterialPageRoute(
                  builder: (_) => const ContinuousStocktakeDialog(),
                ),
              );
              if (count != null && count > 0 && context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text('تم تثبيت جرد $count صنف بنجاح'),
                    backgroundColor: Colors.green,
                  ),
                );
              }
            },
          ),
          IconButton(
            icon: invVm.isSyncing
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                  )
                : const Icon(Icons.sync),
            tooltip: 'مزامنة الطابور غير المتصل',
            onPressed: invVm.isSyncing
                ? null
                : () async {
                    final res = await invVm.syncQueue();
                    if (context.mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(
                          content: Text(
                            'تمت المزامنة بنجاح: ${res.successCount} عملية، تعارض: ${res.conflictCount}',
                          ),
                          duration: const Duration(seconds: 2),
                        ),
                      );
                    }
                  },
          ),
          IconButton(
            icon: const Icon(Icons.qr_code_scanner),
            tooltip: l10n.scanBarcode,
            onPressed: _openCameraScanner,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => invVm.loadInventory(),
        child: Column(
          children: [
            // KPI Summary Chips
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              child: Row(
                children: [
                  Expanded(
                    child: _buildMetricCard(
                      label: 'إجمالي الأصناف',
                      value: '${invVm.products.length}',
                      color: AppColors.primary,
                      isDark: isDark,
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: _buildMetricCard(
                      label: l10n.filterLowStock,
                      value: '${invVm.lowStockCount}',
                      color: Colors.amber[700]!,
                      isDark: isDark,
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: _buildMetricCard(
                      label: l10n.filterOutOfStock,
                      value: '${invVm.outOfStockCount}',
                      color: Colors.red[600]!,
                      isDark: isDark,
                    ),
                  ),
                ],
              ),
            ),

            // Search Bar & Filters
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: TextField(
                controller: _searchController,
                decoration: InputDecoration(
                  hintText: l10n.searchInventoryHint,
                  prefixIcon: const Icon(Icons.search),
                  suffixIcon: _searchController.text.isNotEmpty
                      ? IconButton(
                          icon: const Icon(Icons.clear),
                          onPressed: () {
                            _searchController.clear();
                            invVm.setSearchQuery('');
                          },
                        )
                      : null,
                  filled: true,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                    borderSide: BorderSide.none,
                  ),
                  contentPadding: const EdgeInsets.symmetric(vertical: 0, horizontal: 16),
                ),
                onChanged: (val) => invVm.setSearchQuery(val),
              ),
            ),
            const SizedBox(height: 8),

            // Filter Chips
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Row(
                children: [
                  FilterChip(
                    label: Text(l10n.filterAll),
                    selected: !invVm.lowStockOnly,
                    onSelected: (val) {
                      if (val) invVm.setLowStockOnly(false);
                    },
                  ),
                  const SizedBox(width: 8),
                  FilterChip(
                    label: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.warning_amber_rounded, size: 16, color: Colors.amber),
                        const SizedBox(width: 4),
                        Text(l10n.filterLowStock),
                      ],
                    ),
                    selected: invVm.lowStockOnly,
                    onSelected: (val) => invVm.setLowStockOnly(val),
                  ),
                ],
              ),
            ),
            const Divider(height: 16),

            // Products List
            Expanded(
              child: invVm.isLoading && invVm.products.isEmpty
                  ? const Center(child: CircularProgressIndicator())
                  : invVm.products.isEmpty
                      ? Center(
                          child: Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Icon(
                                Icons.inventory_2_outlined,
                                size: 54,
                                color: isDark ? Colors.grey[600] : Colors.grey[400],
                              ),
                              const SizedBox(height: 12),
                              const Text('لا توجد أصناف تطابق البحث'),
                            ],
                          ),
                        )
                      : ListView.separated(
                          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                          itemCount: invVm.products.length,
                          separatorBuilder: (_, __) => const SizedBox(height: 8),
                          itemBuilder: (context, index) {
                            final product = invVm.products[index];
                            return _buildProductCard(context, product, isDark, l10n);
                          },
                        ),
            ),
          ],
        ),
      ),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.add),
        label: Text(l10n.addProduct),
        onPressed: () => _showAddProductDialog(context),
      ),
    );
  }

  Widget _buildMetricCard({
    required String label,
    required String value,
    required Color color,
    required bool isDark,
  }) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 8),
      decoration: BoxDecoration(
        color: color.withValues(alpha: isDark ? 0.18 : 0.08),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withValues(alpha: 0.25)),
      ),
      child: Column(
        children: [
          Text(
            value,
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.bold,
              color: color,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            label,
            style: TextStyle(
              fontSize: 11,
              color: isDark ? Colors.grey[300] : Colors.grey[700],
            ),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    );
  }

  Widget _buildProductCard(
    BuildContext context,
    Product product,
    bool isDark,
    AppLocalizations l10n,
  ) {
    Color stockColor;
    String stockLabel;
    if (product.stockQuantity == 0) {
      stockColor = Colors.red;
      stockLabel = 'نفد المخزون';
    } else if (product.stockQuantity <= 5) {
      stockColor = Colors.amber[800]!;
      stockLabel = 'مخزون منخفض (${product.stockQuantity})';
    } else {
      stockColor = Colors.green;
      stockLabel = '${product.stockQuantity} متوفر';
    }

    return Card(
      elevation: 0.5,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        product.name,
                        style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
                      ),
                      const SizedBox(height: 4),
                      Row(
                        children: [
                          if (product.barcode != null) ...[
                            Icon(Icons.qr_code, size: 14, color: isDark ? Colors.grey[400] : Colors.grey[600]),
                            const SizedBox(width: 4),
                            Text(
                              product.barcode!,
                              style: TextStyle(fontSize: 11, color: isDark ? Colors.grey[400] : Colors.grey[600]),
                            ),
                            const SizedBox(width: 12),
                          ],
                          if (product.sku != null) ...[
                            Text(
                              'SKU: ${product.sku}',
                              style: TextStyle(fontSize: 11, color: isDark ? Colors.grey[400] : Colors.grey[600]),
                            ),
                          ],
                        ],
                      ),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: stockColor.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: stockColor.withValues(alpha: 0.3)),
                  ),
                  child: Text(
                    stockLabel,
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.bold,
                      color: stockColor,
                    ),
                  ),
                ),
              ],
            ),
            const Divider(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  '${product.price} ر.س',
                  style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
                ),
                Row(
                  children: [
                    OutlinedButton.icon(
                      style: OutlinedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                        minimumSize: Size.zero,
                        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      ),
                      icon: const Icon(Icons.fact_check, size: 14),
                      label: Text(l10n.stockCount, style: const TextStyle(fontSize: 12)),
                      onPressed: () => _showCountDialog(context, product),
                    ),
                    const SizedBox(width: 8),
                    ElevatedButton.icon(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppColors.primary,
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                        minimumSize: Size.zero,
                        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      ),
                      icon: const Icon(Icons.tune, size: 14),
                      label: Text(l10n.adjustStock, style: const TextStyle(fontSize: 12)),
                      onPressed: () => _showAdjustDialog(context, product),
                    ),
                  ],
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
