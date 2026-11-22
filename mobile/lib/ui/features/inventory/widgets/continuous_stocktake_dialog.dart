import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:provider/provider.dart';
import '../../../../core/constants/app_colors.dart';
import '../../../../data/models/product.dart';
import '../../../../providers/inventory_view_model.dart';

class ContinuousStocktakeDialog extends StatefulWidget {
  const ContinuousStocktakeDialog({super.key});

  @override
  State<ContinuousStocktakeDialog> createState() => _ContinuousStocktakeDialogState();
}

class _ScannedStockEntry {
  final Product product;
  int countedQuantity;

  _ScannedStockEntry({
    required this.product,
    required this.countedQuantity,
  });

  int get systemQuantity => product.stockQuantity;
  int get variance => countedQuantity - systemQuantity;
}

class _ContinuousStocktakeDialogState extends State<ContinuousStocktakeDialog> {
  final MobileScannerController _controller = MobileScannerController(
    detectionSpeed: DetectionSpeed.normal,
    facing: CameraFacing.back,
    torchEnabled: false,
  );

  final Map<String, _ScannedStockEntry> _scannedItems = {};
  final TextEditingController _manualInputController = TextEditingController();

  bool _torchOn = false;
  bool _isCommitting = false;
  String? _lastScannedBarcode;
  DateTime? _lastScanTime;
  String? _bannerMessage;

  @override
  void dispose() {
    _controller.dispose();
    _manualInputController.dispose();
    super.dispose();
  }

  void _processBarcode(String barcode) {
    final now = DateTime.now();
    // Debounce: prevent same barcode scanning within 1200ms
    if (_lastScannedBarcode == barcode &&
        _lastScanTime != null &&
        now.difference(_lastScanTime!).inMilliseconds < 1200) {
      return;
    }

    _lastScannedBarcode = barcode;
    _lastScanTime = now;

    final invVm = context.read<InventoryViewModel>();
    Product? found;
    try {
      found = invVm.products.firstWhere(
        (p) =>
            p.barcode?.trim() == barcode.trim() ||
            p.sku?.trim() == barcode.trim() ||
            p.id == barcode.trim(),
      );
    } catch (_) {
      found = null;
    }

    setState(() {
      if (found != null) {
        if (_scannedItems.containsKey(found.id)) {
          _scannedItems[found.id]!.countedQuantity += 1;
        } else {
          _scannedItems[found.id] = _ScannedStockEntry(
            product: found,
            countedQuantity: 1,
          );
        }
        _bannerMessage = 'تم حصر: ${found.name} (${_scannedItems[found.id]!.countedQuantity})';
      } else {
        _bannerMessage = 'باركود غير مسجل في المخزون: $barcode';
      }
    });

    // Auto-clear banner after 2.5 seconds
    Future.delayed(const Duration(milliseconds: 2500), () {
      if (mounted) {
        setState(() {
          if (_bannerMessage != null && _bannerMessage!.contains(barcode)) {
            _bannerMessage = null;
          }
        });
      }
    });
  }

  void _onDetect(BarcodeCapture capture) {
    for (final barcode in capture.barcodes) {
      final code = barcode.rawValue;
      if (code != null && code.trim().isNotEmpty) {
        _processBarcode(code.trim());
        break;
      }
    }
  }

  Future<void> _commitStocktake() async {
    if (_scannedItems.isEmpty) return;

    setState(() {
      _isCommitting = true;
    });

    final invVm = context.read<InventoryViewModel>();
    int successCount = 0;

    for (final entry in _scannedItems.values) {
      final ok = await invVm.countStock(
        product: entry.product,
        countedQuantity: entry.countedQuantity,
      );
      if (ok) successCount++;
    }

    if (mounted) {
      setState(() {
        _isCommitting = false;
      });
      Navigator.pop(context, successCount);
    }
  }

  int get _totalDistinct => _scannedItems.length;
  int get _totalUnits =>
      _scannedItems.values.fold<int>(0, (sum, item) => sum + item.countedQuantity);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    return Scaffold(
      appBar: AppBar(
        title: const Text('الجرد المتتابع بالماسح'),
        actions: [
          IconButton(
            icon: Icon(_torchOn ? Icons.flash_on : Icons.flash_off),
            tooltip: 'الفلاش',
            onPressed: () async {
              await _controller.toggleTorch();
              setState(() {
                _torchOn = !_torchOn;
              });
            },
          ),
          IconButton(
            icon: const Icon(Icons.flip_camera_ios),
            tooltip: 'تبديل الكاميرا',
            onPressed: () => _controller.switchCamera(),
          ),
        ],
      ),
      body: Column(
        children: [
          // 1. Camera Viewport (Upper Half)
          SizedBox(
            height: 220,
            child: Stack(
              alignment: Alignment.center,
              children: [
                MobileScanner(
                  controller: _controller,
                  onDetect: _onDetect,
                  errorBuilder: (context, error) {
                    return Container(
                      color: Colors.black87,
                      padding: const EdgeInsets.all(16),
                      child: Center(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Icon(Icons.videocam_off, color: Colors.white70, size: 40),
                            const SizedBox(height: 8),
                            const Text(
                              'تعذر تشغيل الكاميرا - يمكنك الإدخال اليدوي أدناه',
                              style: TextStyle(color: Colors.white70, fontSize: 13),
                              textAlign: TextAlign.center,
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
                // Aim reticle box
                Container(
                  width: 240,
                  height: 120,
                  decoration: BoxDecoration(
                    border: Border.all(color: AppColors.primary, width: 2),
                    borderRadius: BorderRadius.circular(12),
                  ),
                ),
                // Top feedback banner
                if (_bannerMessage != null)
                  Positioned(
                    top: 10,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
                      decoration: BoxDecoration(
                        color: _bannerMessage!.startsWith('تم حصر')
                            ? Colors.green.shade800
                            : Colors.orange.shade900,
                        borderRadius: BorderRadius.circular(20),
                        boxShadow: const [
                          BoxShadow(color: Colors.black26, blurRadius: 4, offset: Offset(0, 2)),
                        ],
                      ),
                      child: Text(
                        _bannerMessage!,
                        style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.bold,
                          fontSize: 12,
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),

          // 2. Manual barcode input bar
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _manualInputController,
                    decoration: InputDecoration(
                      hintText: 'إدخال يدوي للباركود أو SKU...',
                      isDense: true,
                      prefixIcon: const Icon(Icons.qr_code, size: 20),
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                    ),
                    onSubmitted: (val) {
                      if (val.trim().isNotEmpty) {
                        _processBarcode(val.trim());
                        _manualInputController.clear();
                      }
                    },
                  ),
                ),
                const SizedBox(width: 8),
                ElevatedButton(
                  onPressed: () {
                    final val = _manualInputController.text;
                    if (val.trim().isNotEmpty) {
                      _processBarcode(val.trim());
                      _manualInputController.clear();
                    }
                  },
                  child: const Text('إضافة'),
                ),
              ],
            ),
          ),

          // 3. Stocktake Summary Bar
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            color: isDark ? Colors.grey.shade900 : Colors.grey.shade100,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  'الأصناف المجرودة: $_totalDistinct',
                  style: const TextStyle(fontWeight: FontWeight.bold),
                ),
                Text(
                  'إجمالي الوحدات: $_totalUnits',
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    color: AppColors.primary,
                  ),
                ),
              ],
            ),
          ),

          // 4. Scanned items list
          Expanded(
            child: _scannedItems.isEmpty
              ? Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.barcode_reader, size: 64, color: Colors.grey.shade400),
                      const SizedBox(height: 12),
                      const Text(
                        'وجّه الكاميرا نحو باركود المنتجات للجرد المتتابع',
                        style: TextStyle(color: Colors.grey, fontSize: 14),
                      ),
                      const SizedBox(height: 4),
                      const Text(
                        'سيتم تجميع الكميات تلقائياً دون مغادرة الشاشة',
                        style: TextStyle(color: Colors.grey, fontSize: 12),
                      ),
                    ],
                  ),
                )
              : ListView.separated(
                  padding: const EdgeInsets.all(12),
                  itemCount: _scannedItems.length,
                  separatorBuilder: (_, __) => const Divider(height: 1),
                  itemBuilder: (context, idx) {
                    final item = _scannedItems.values.elementAt(idx);
                    final variance = item.variance;

                    return Card(
                      margin: const EdgeInsets.symmetric(vertical: 4),
                      child: Padding(
                        padding: const EdgeInsets.all(12),
                        child: Row(
                          children: [
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    item.product.name,
                                    style: const TextStyle(
                                      fontWeight: FontWeight.bold,
                                      fontSize: 14,
                                    ),
                                  ),
                                  const SizedBox(height: 4),
                                  Text(
                                    'باركود: ${item.product.barcode ?? "—"} | النظام: ${item.systemQuantity}',
                                    style: TextStyle(
                                      fontSize: 12,
                                      color: isDark ? Colors.white60 : Colors.black54,
                                    ),
                                  ),
                                  const SizedBox(height: 4),
                                  Row(
                                    children: [
                                      Text(
                                        'الفارق: ',
                                        style: TextStyle(
                                          fontSize: 12,
                                          color: isDark ? Colors.white60 : Colors.black54,
                                        ),
                                      ),
                                      Text(
                                        variance == 0
                                            ? 'مطابق'
                                            : variance > 0
                                                ? '+$variance (فائض)'
                                                : '$variance (عجز)',
                                        style: TextStyle(
                                          fontSize: 12,
                                          fontWeight: FontWeight.bold,
                                          color: variance == 0
                                              ? Colors.green
                                              : variance > 0
                                                  ? Colors.blue
                                                  : Colors.red,
                                        ),
                                      ),
                                    ],
                                  ),
                                ],
                              ),
                            ),
                            // Counter controls
                            Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                IconButton(
                                  icon: const Icon(Icons.remove_circle_outline, size: 22),
                                  onPressed: () {
                                    setState(() {
                                      if (item.countedQuantity > 1) {
                                        item.countedQuantity--;
                                      } else {
                                        _scannedItems.remove(item.product.id);
                                      }
                                    });
                                  },
                                ),
                                Container(
                                  constraints: const BoxConstraints(minWidth: 32),
                                  alignment: Alignment.center,
                                  child: Text(
                                    '${item.countedQuantity}',
                                    style: const TextStyle(
                                      fontSize: 16,
                                      fontWeight: FontWeight.bold,
                                    ),
                                  ),
                                ),
                                IconButton(
                                  icon: const Icon(Icons.add_circle_outline, size: 22, color: AppColors.primary),
                                  onPressed: () {
                                    setState(() {
                                      item.countedQuantity++;
                                    });
                                  },
                                ),
                                IconButton(
                                  icon: const Icon(Icons.delete_outline, size: 20, color: Colors.grey),
                                  onPressed: () {
                                    setState(() {
                                      _scannedItems.remove(item.product.id);
                                    });
                                  },
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
          ),

          // 5. Commit Action Footer
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: isDark ? Colors.grey.shade900 : Colors.white,
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.05),
                  blurRadius: 6,
                  offset: const Offset(0, -2),
                ),
              ],
            ),
            child: SafeArea(
              child: SizedBox(
                width: double.infinity,
                height: 48,
                child: ElevatedButton.icon(
                  icon: _isCommitting
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2),
                        )
                      : const Icon(Icons.check_circle_outline),
                  label: Text(
                    _isCommitting
                        ? 'جاري حفظ الجرد...'
                        : 'تثبيت الجرد ($_totalDistinct صنف / $_totalUnits وحدة)',
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.primary,
                    foregroundColor: Colors.white,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                  onPressed: _scannedItems.isEmpty || _isCommitting ? null : _commitStocktake,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
