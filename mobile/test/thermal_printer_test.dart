import 'package:flutter_test/flutter_test.dart';
import 'package:fihrist_mobile/core/printer/receipt_printer_service.dart';
import 'package:fihrist_mobile/core/printer/thermal_printer_manager.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('ThermalPrinterManager & ESC/POS', () {
    test('ReceiptPrinterService generates openCashDrawerBytes with ESC p pulse', () {
      final bytes = ReceiptPrinterService.openCashDrawerBytes();
      expect(bytes, isNotEmpty);
      expect(bytes.length, 5);
      // ESC p 0 25 250
      expect(bytes[0], 0x1B);
      expect(bytes[1], 0x70);
      expect(bytes[2], 0x00);
      expect(bytes[3], 0x19);
      expect(bytes[4], 0xFA);
    });

    test('ThermalPrinterConfig copyWith updates fields properly', () {
      const config = ThermalPrinterConfig();
      expect(config.paperWidth, PaperWidth.mm80);
      expect(config.connectionType, PrinterConnectionType.preview);
      expect(config.autoKickCashDrawer, isTrue);

      final updated = config.copyWith(
        paperWidth: PaperWidth.mm58,
        connectionType: PrinterConnectionType.network,
        deviceAddress: '192.168.1.200',
        networkPort: 9200,
        autoKickCashDrawer: false,
      );

      expect(updated.paperWidth, PaperWidth.mm58);
      expect(updated.connectionType, PrinterConnectionType.network);
      expect(updated.deviceAddress, '192.168.1.200');
      expect(updated.networkPort, 9200);
      expect(updated.autoKickCashDrawer, isFalse);
    });
  });
}
