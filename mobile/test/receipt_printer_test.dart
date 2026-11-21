import 'package:flutter_test/flutter_test.dart';
import 'package:fihrist_mobile/core/printer/receipt_printer_service.dart';
import 'package:fihrist_mobile/data/models/product.dart';

void main() {
  group('ReceiptPrinterService', () {
    test('generateTextReceipt formats simplified tax invoice correctly', () {
      final items = [
        CartItem(
          product: const Product(
            id: 'p1',
            name: 'قهوة عربي فاخرة',
            price: '35.00',
          ),
          quantity: 2,
        ),
      ];

      final receipt = ReceiptPrinterService.generateTextReceipt(
        storeName: 'متجر فهرست التجريبي',
        vatNumber: '300123456700003',
        receiptNumber: 'REC-998877',
        timestamp: DateTime(2026, 11, 21, 10, 30),
        items: items,
        subtotal: '70.00',
        tax: '10.50',
        total: '80.50',
        paymentMethod: 'cash',
        cashierName: 'أحمد',
      );

      expect(receipt, contains('متجر فهرست التجريبي'));
      expect(receipt, contains('فاتورة ضريبية مبسطة'));
      expect(receipt, contains('300123456700003'));
      expect(receipt, contains('REC-998877'));
      expect(receipt, contains('قهوة عربي فاخرة'));
      expect(receipt, contains('70.00 ر.س'));
      expect(receipt, contains('10.50 ر.س'));
      expect(receipt, contains('80.50 ر.س'));
      expect(receipt, contains('ZATCA QR'));
      expect(receipt, contains('شكراً لزيارتكم ونسعد بخدمتكم'));
    });

    test('generateEscPosBytes returns non-empty byte buffer with ESC/POS headers', () {
      final items = [
        CartItem(
          product: const Product(
            id: 'p1',
            name: 'تمر سكري',
            price: '65.00',
          ),
          quantity: 1,
        ),
      ];

      final bytes = ReceiptPrinterService.generateEscPosBytes(
        storeName: 'فهرست',
        receiptNumber: 'REC-1',
        timestamp: DateTime.now(),
        items: items,
        subtotal: '65.00',
        tax: '9.75',
        total: '74.75',
        paymentMethod: 'card',
      );

      expect(bytes.isNotEmpty, true);
      // ESC @ is [0x1B, 0x40]
      expect(bytes[0], 0x1B);
      expect(bytes[1], 0x40);
    });
  });
}
