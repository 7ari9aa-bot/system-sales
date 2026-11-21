import 'dart:convert';
import 'dart:typed_data';
import '../utils/money_formatter.dart';
import '../zatca/zatca_qr_service.dart';
import '../../data/models/product.dart';

class ReceiptPrinterService {
  /// Generates human-readable thermal receipt text
  static String generateTextReceipt({
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
  }) {
    final buffer = StringBuffer();
    final divider = '--------------------------------';

    buffer.writeln('================================');
    buffer.writeln(_centerText(storeName, 32));
    buffer.writeln(_centerText('فاتورة ضريبية مبسطة', 32));
    if (vatNumber != null && vatNumber.isNotEmpty) {
      buffer.writeln(_centerText('الرقم الضريبي: $vatNumber', 32));
    }
    buffer.writeln('================================');
    buffer.writeln('رقم الفاتورة : $receiptNumber');
    buffer.writeln('التاريخ       : ${_formatDateTime(timestamp)}');
    if (cashierName != null) {
      buffer.writeln('الكاشير       : $cashierName');
    }
    buffer.writeln('طريقة الدفع  : ${paymentMethod == 'cash' ? 'نقدي' : 'بطاقة / مدى'}');
    buffer.writeln(divider);
    buffer.writeln('المنتج             الكمية  الإجمالي');
    buffer.writeln(divider);

    for (final item in items) {
      final name = item.product.name.length > 16
          ? '${item.product.name.substring(0, 14)}..'
          : item.product.name.padRight(16);
      final qty = '${item.quantity}'.padLeft(4);
      final lineTot = MoneyFormatter.format(item.lineTotal, currency: 'ر.س').padLeft(10);
      buffer.writeln('$name $qty $lineTot');
    }

    buffer.writeln(divider);
    buffer.writeln('المجموع الفرعي : ${MoneyFormatter.format(subtotal, currency: 'ر.س')}');
    buffer.writeln('ضريبة القيمة المضافة (15%): ${MoneyFormatter.format(tax, currency: 'ر.س')}');
    buffer.writeln('الإجمالي الكلي : ${MoneyFormatter.format(total, currency: 'ر.س')}');
    buffer.writeln('================================');
    
    // ZATCA QR Code Payload
    final zatcaQr = ZatcaQrService.generateBase64Qr(
      sellerName: storeName,
      vatRegistrationNumber: vatNumber ?? '300123456700003',
      timestamp: timestamp,
      invoiceTotalWithVat: total,
      vatTotal: tax,
    );
    buffer.writeln(_centerText('[فاتورة إلكترونية معتمدة - ZATCA QR]', 32));
    buffer.writeln(_wrapText(zatcaQr, 32));
    buffer.writeln('================================');
    buffer.writeln(_centerText('شكراً لزيارتكم ونسعد بخدمتكم', 32));
    buffer.writeln('================================\n\n');

    return buffer.toString();
  }

  /// Generates standard ESC/POS raw bytes for Bluetooth / USB thermal receipt printers
  static Uint8List generateEscPosBytes({
    required String storeName,
    required String receiptNumber,
    required DateTime timestamp,
    required List<CartItem> items,
    required String subtotal,
    required String tax,
    required String total,
    required String paymentMethod,
  }) {
    final bytes = <int>[];

    // ESC @ : Initialize printer
    bytes.addAll([0x1B, 0x40]);

    // ESC a 1 : Align center
    bytes.addAll([0x1B, 0x61, 0x01]);

    // Double height + double width for Title
    bytes.addAll([0x1D, 0x21, 0x11]);
    bytes.addAll(utf8.encode('$storeName\n'));

    // Normal text
    bytes.addAll([0x1D, 0x21, 0x00]);
    bytes.addAll(utf8.encode('Simplified Tax Invoice\n\n'));

    // Left align
    bytes.addAll([0x1B, 0x61, 0x00]);
    final text = generateTextReceipt(
      storeName: storeName,
      vatNumber: '300123456700003',
      receiptNumber: receiptNumber,
      timestamp: timestamp,
      items: items,
      subtotal: subtotal,
      tax: tax,
      total: total,
      paymentMethod: paymentMethod,
    );
    bytes.addAll(utf8.encode(text));

    // Center align for native 2D QR Code print
    bytes.addAll([0x1B, 0x61, 0x01]);
    final zatcaQr = ZatcaQrService.generateBase64Qr(
      sellerName: storeName,
      vatRegistrationNumber: '300123456700003',
      timestamp: timestamp,
      invoiceTotalWithVat: total,
      vatTotal: tax,
    );
    bytes.addAll(ZatcaQrService.generateEscPosQrCommands(zatcaQr));
    bytes.addAll(utf8.encode('\n\n'));

    // Feed and Paper cut (GS V 66 0)
    bytes.addAll([0x1D, 0x56, 0x42, 0x00]);

    return Uint8List.fromList(bytes);
  }

  /// Generates ESC/POS pulse to open cash drawer (ESC p 0 25 250)
  static Uint8List openCashDrawerBytes() {
    return Uint8List.fromList([0x1B, 0x70, 0x00, 0x19, 0xFA]);
  }

  static String _centerText(String text, int width) {
    if (text.length >= width) return text;
    final leftPadding = (width - text.length) ~/ 2;
    return ' ' * leftPadding + text;
  }

  static String _wrapText(String text, int width) {
    final buffer = StringBuffer();
    for (int i = 0; i < text.length; i += width) {
      final end = (i + width < text.length) ? i + width : text.length;
      buffer.writeln(text.substring(i, end));
    }
    return buffer.toString().trimRight();
  }

  static String _formatDateTime(DateTime dt) {
    return '${dt.year}-${dt.month.toString().padLeft(2, '0')}-${dt.day.toString().padLeft(2, '0')} ${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  }
}
