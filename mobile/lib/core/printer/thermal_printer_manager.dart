import 'dart:async';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../../data/models/product.dart';
import 'receipt_printer_service.dart';

enum PrinterConnectionType {
  preview,
  bluetooth,
  network,
}

enum PaperWidth {
  mm58, // 32 characters
  mm80, // 48 characters
}

class ThermalPrinterConfig {
  final PrinterConnectionType connectionType;
  final String deviceName;
  final String deviceAddress; // Bluetooth MAC or Network IP
  final int networkPort; // Default 9100 for ESC/POS
  final PaperWidth paperWidth;
  final bool autoKickCashDrawer;

  const ThermalPrinterConfig({
    this.connectionType = PrinterConnectionType.preview,
    this.deviceName = 'الطابعة الافتراضية',
    this.deviceAddress = '192.168.1.100',
    this.networkPort = 9100,
    this.paperWidth = PaperWidth.mm80,
    this.autoKickCashDrawer = true,
  });

  ThermalPrinterConfig copyWith({
    PrinterConnectionType? connectionType,
    String? deviceName,
    String? deviceAddress,
    int? networkPort,
    PaperWidth? paperWidth,
    bool? autoKickCashDrawer,
  }) {
    return ThermalPrinterConfig(
      connectionType: connectionType ?? this.connectionType,
      deviceName: deviceName ?? this.deviceName,
      deviceAddress: deviceAddress ?? this.deviceAddress,
      networkPort: networkPort ?? this.networkPort,
      paperWidth: paperWidth ?? this.paperWidth,
      autoKickCashDrawer: autoKickCashDrawer ?? this.autoKickCashDrawer,
    );
  }
}

class ThermalPrinterManager extends ChangeNotifier {
  static const String _prefKeyConnType = 'printer_conn_type';
  static const String _prefKeyName = 'printer_device_name';
  static const String _prefKeyAddress = 'printer_device_address';
  static const String _prefKeyPort = 'printer_network_port';
  static const String _prefKeyPaper = 'printer_paper_width';
  static const String _prefKeyDrawer = 'printer_auto_drawer';

  ThermalPrinterConfig _config = const ThermalPrinterConfig();
  bool _isPrinting = false;
  String? _lastError;

  ThermalPrinterConfig get config => _config;
  bool get isPrinting => _isPrinting;
  String? get lastError => _lastError;

  ThermalPrinterManager() {
    loadSettings();
  }

  Future<void> loadSettings() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final connTypeStr = prefs.getString(_prefKeyConnType) ?? 'preview';
      final name = prefs.getString(_prefKeyName) ?? 'الطابعة الافتراضية';
      final address = prefs.getString(_prefKeyAddress) ?? '192.168.1.100';
      final port = prefs.getInt(_prefKeyPort) ?? 9100;
      final paperStr = prefs.getString(_prefKeyPaper) ?? '80mm';
      final drawer = prefs.getBool(_prefKeyDrawer) ?? true;

      final connType = PrinterConnectionType.values.firstWhere(
        (e) => e.name == connTypeStr,
        orElse: () => PrinterConnectionType.preview,
      );

      final paper = paperStr == '58mm' ? PaperWidth.mm58 : PaperWidth.mm80;

      _config = ThermalPrinterConfig(
        connectionType: connType,
        deviceName: name,
        deviceAddress: address,
        networkPort: port,
        paperWidth: paper,
        autoKickCashDrawer: drawer,
      );
      notifyListeners();
    } catch (_) {}
  }

  Future<void> updateConfig(ThermalPrinterConfig newConfig) async {
    _config = newConfig;
    notifyListeners();

    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_prefKeyConnType, _config.connectionType.name);
      await prefs.setString(_prefKeyName, _config.deviceName);
      await prefs.setString(_prefKeyAddress, _config.deviceAddress);
      await prefs.setInt(_prefKeyPort, _config.networkPort);
      await prefs.setString(
        _prefKeyPaper,
        _config.paperWidth == PaperWidth.mm58 ? '58mm' : '80mm',
      );
      await prefs.setBool(_prefKeyDrawer, _config.autoKickCashDrawer);
    } catch (_) {}
  }

  /// Sends raw ESC/POS bytes over network socket or simulated channel
  Future<bool> sendRawBytes(Uint8List bytes) async {
    _isPrinting = true;
    _lastError = null;
    notifyListeners();

    try {
      if (_config.connectionType == PrinterConnectionType.network) {
        // Direct ESC/POS network print over TCP socket (Port 9100)
        final socket = await Socket.connect(
          _config.deviceAddress,
          _config.networkPort,
          timeout: const Duration(seconds: 4),
        );
        socket.add(bytes);
        await socket.flush();
        await socket.close();
        return true;
      } else {
        // Bluetooth / Preview: simulated immediate write
        await Future.delayed(const Duration(milliseconds: 300));
        return true;
      }
    } catch (e) {
      _lastError = 'تعذر الاتصال بالطابعة: $e';
      return false;
    } finally {
      _isPrinting = false;
      notifyListeners();
    }
  }

  /// Prints a simplified tax receipt
  Future<bool> printReceipt({
    required String storeName,
    required String? vatNumber,
    required String receiptNumber,
    required DateTime timestamp,
    required List<CartItem> items,
    required String subtotal,
    required String tax,
    required String total,
    required String paymentMethod,
    String? cashierName,
  }) async {
    final bytes = ReceiptPrinterService.generateEscPosBytes(
      storeName: storeName,
      receiptNumber: receiptNumber,
      timestamp: timestamp,
      items: items,
      subtotal: subtotal,
      tax: tax,
      total: total,
      paymentMethod: paymentMethod,
    );

    final success = await sendRawBytes(bytes);

    // Kick cash drawer if configured and payment is cash
    if (success && _config.autoKickCashDrawer && paymentMethod == 'cash') {
      await kickCashDrawer();
    }

    return success;
  }

  /// Sends ESC/POS cash drawer kick pulse
  Future<bool> kickCashDrawer() async {
    final drawerBytes = ReceiptPrinterService.openCashDrawerBytes();
    return await sendRawBytes(drawerBytes);
  }

  /// Prints a test receipt to verify connection
  Future<bool> printTestReceipt({required String storeName}) async {
    final testItem = CartItem(
      product: Product(
        id: 'test-1',
        name: 'منتج تجريبي (Test Item)',
        sku: 'TEST-001',
        price: '10.00',
        stockQuantity: 99,
        category: 'عام',
      ),
      quantity: 1,
    );

    return await printReceipt(
      storeName: storeName,
      vatNumber: '300123456700003',
      receiptNumber: 'TEST-${DateTime.now().millisecondsSinceEpoch}',
      timestamp: DateTime.now(),
      items: [testItem],
      subtotal: '10.00',
      tax: '1.50',
      total: '11.50',
      paymentMethod: 'cash',
      cashierName: 'فاحص الطابعة',
    );
  }
}
