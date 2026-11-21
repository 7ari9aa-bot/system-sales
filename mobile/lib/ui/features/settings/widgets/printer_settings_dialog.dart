import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../../core/constants/app_colors.dart';
import '../../../../core/printer/thermal_printer_manager.dart';
import '../../../../providers/auth_view_model.dart';

class PrinterSettingsDialog extends StatefulWidget {
  const PrinterSettingsDialog({super.key});

  @override
  State<PrinterSettingsDialog> createState() => _PrinterSettingsDialogState();
}

class _PrinterSettingsDialogState extends State<PrinterSettingsDialog> {
  late PrinterConnectionType _connectionType;
  late TextEditingController _nameController;
  late TextEditingController _addressController;
  late TextEditingController _portController;
  late PaperWidth _paperWidth;
  late bool _autoDrawer;

  @override
  void initState() {
    super.initState();
    final manager = context.read<ThermalPrinterManager>();
    final config = manager.config;
    _connectionType = config.connectionType;
    _nameController = TextEditingController(text: config.deviceName);
    _addressController = TextEditingController(text: config.deviceAddress);
    _portController = TextEditingController(text: config.networkPort.toString());
    _paperWidth = config.paperWidth;
    _autoDrawer = config.autoKickCashDrawer;
  }

  @override
  void dispose() {
    _nameController.dispose();
    _addressController.dispose();
    _portController.dispose();
    super.dispose();
  }

  Future<void> _saveConfig() async {
    final manager = context.read<ThermalPrinterManager>();
    final newConfig = ThermalPrinterConfig(
      connectionType: _connectionType,
      deviceName: _nameController.text.trim(),
      deviceAddress: _addressController.text.trim(),
      networkPort: int.tryParse(_portController.text.trim()) ?? 9100,
      paperWidth: _paperWidth,
      autoKickCashDrawer: _autoDrawer,
    );
    await manager.updateConfig(newConfig);
    if (mounted) {
      Navigator.pop(context);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('تم حفظ إعدادات الطابعة بنجاح'),
          backgroundColor: AppColors.success,
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final manager = context.watch<ThermalPrinterManager>();
    final authVm = context.read<AuthViewModel>();

    return AlertDialog(
      title: const Row(
        children: [
          Icon(Icons.print, color: AppColors.primary),
          SizedBox(width: 8),
          Text('إعدادات الطابعة الحرارية'),
        ],
      ),
      content: SingleChildScrollView(
        child: SizedBox(
          width: 440,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Connection Type Dropdown
              const Text('نوع الاتصال بالطابعة:', style: TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 6),
              DropdownButtonFormField<PrinterConnectionType>(
                value: _connectionType,
                decoration: const InputDecoration(
                  contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                ),
                items: const [
                  DropdownMenuItem(
                    value: PrinterConnectionType.preview,
                    child: Text('معاينة رقمية (محاكاة الشاشة)'),
                  ),
                  DropdownMenuItem(
                    value: PrinterConnectionType.bluetooth,
                    child: Text('طابعة بلوتوث حرارية (Bluetooth ESC/POS)'),
                  ),
                  DropdownMenuItem(
                    value: PrinterConnectionType.network,
                    child: Text('طابعة شبكة WiFi / LAN (ESC/POS Port 9100)'),
                  ),
                ],
                onChanged: (val) {
                  if (val != null) setState(() => _connectionType = val);
                },
              ),
              const SizedBox(height: 14),

              // Device Name
              const Text('اسم الطابعة:', style: TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 6),
              TextField(
                controller: _nameController,
                decoration: const InputDecoration(
                  hintText: 'مثال: POS-80 Thermal Printer',
                  prefixIcon: Icon(Icons.devices),
                ),
              ),
              const SizedBox(height: 14),

              // Network IP or Bluetooth Device
              if (_connectionType == PrinterConnectionType.network) ...[
                const Text('عنوان IP في الشبكة المحلية:', style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 6),
                TextField(
                  controller: _addressController,
                  keyboardType: TextInputType.url,
                  decoration: const InputDecoration(
                    hintText: '192.168.1.100',
                    prefixIcon: Icon(Icons.wifi),
                  ),
                ),
                const SizedBox(height: 14),
                const Text('المنفذ (Port):', style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 6),
                TextField(
                  controller: _portController,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                    hintText: '9100',
                    prefixIcon: Icon(Icons.numbers),
                  ),
                ),
                const SizedBox(height: 14),
              ] else if (_connectionType == PrinterConnectionType.bluetooth) ...[
                const Text('اسم أو معرف جهاز البلوتوث:', style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 6),
                TextField(
                  controller: _addressController,
                  decoration: const InputDecoration(
                    hintText: 'MTP-II / RPP02N / BlueTooth Printer',
                    prefixIcon: Icon(Icons.bluetooth),
                  ),
                ),
                const SizedBox(height: 14),
              ],

              // Paper Width
              const Text('مقاس ورق الفاتورة:', style: TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 6),
              SegmentedButton<PaperWidth>(
                segments: const [
                  ButtonSegment(
                    value: PaperWidth.mm80,
                    label: Text('80 مم (قياسي)'),
                    icon: Icon(Icons.receipt_long),
                  ),
                  ButtonSegment(
                    value: PaperWidth.mm58,
                    label: Text('58 مم (صغير)'),
                    icon: Icon(Icons.receipt),
                  ),
                ],
                selected: {_paperWidth},
                onSelectionChanged: (val) {
                  setState(() => _paperWidth = val.first);
                },
              ),
              const SizedBox(height: 14),

              // Auto Drawer Kick
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('فتح درج الكاشير تلقائياً عند الدفع النقدي'),
                subtitle: const Text('يرسل نبضة ESC/POS للدرج المتصل بالطابعة'),
                value: _autoDrawer,
                onChanged: (val) => setState(() => _autoDrawer = val),
              ),
              const SizedBox(height: 16),

              // Action buttons (Test Print & Kick Drawer)
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      icon: manager.isPrinting
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.print_outlined, size: 18),
                      label: const Text('اختبار الطباعة'),
                      onPressed: manager.isPrinting
                          ? null
                          : () async {
                              final ok = await manager.printTestReceipt(
                                storeName: authVm.currentUser?.tenantName ?? 'متجر فهرست',
                              );
                              if (context.mounted) {
                                ScaffoldMessenger.of(context).showSnackBar(
                                  SnackBar(
                                    content: Text(ok
                                        ? 'تم إرسال إيصال الاختبار بنجاح'
                                        : (manager.lastError ?? 'فشل اختبار الطباعة')),
                                    backgroundColor: ok ? AppColors.success : AppColors.error,
                                  ),
                                );
                              }
                            },
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: OutlinedButton.icon(
                      icon: const Icon(Icons.point_of_sale, size: 18),
                      label: const Text('فتح الدرج'),
                      onPressed: manager.isPrinting
                          ? null
                          : () async {
                              final ok = await manager.kickCashDrawer();
                              if (context.mounted) {
                                ScaffoldMessenger.of(context).showSnackBar(
                                  SnackBar(
                                    content: Text(ok ? 'تم إرسال نبضة فتح درج النقد' : 'فشل الاتصال'),
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
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('إلغاء'),
        ),
        ElevatedButton(
          onPressed: _saveConfig,
          child: const Text('حفظ التعديلات'),
        ),
      ],
    );
  }
}
