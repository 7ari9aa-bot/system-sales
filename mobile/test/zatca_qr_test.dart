import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:fihrist_mobile/core/zatca/zatca_qr_service.dart';

void main() {
  group('ZatcaQrService (هيئة الزكاة والضريبة والجمارك)', () {
    final testDate = DateTime.utc(2026, 11, 21, 14, 0, 0);

    test('encodes and decodes standard ZATCA Phase 1 TLV fields', () {
      final tlvBytes = ZatcaQrService.encodeTlv(
        sellerName: 'شركة فهرست للتجارة',
        vatRegistrationNumber: '300123456700003',
        timestamp: testDate,
        invoiceTotalWithVat: '115.00',
        vatTotal: '15.00',
      );

      expect(tlvBytes, isNotEmpty);

      final decoded = ZatcaQrService.decodeTlv(tlvBytes);
      expect(decoded[1], 'شركة فهرست للتجارة');
      expect(decoded[2], '300123456700003');
      expect(decoded[3], '2026-11-21T14:00:00Z');
      expect(decoded[4], '115.00');
      expect(decoded[5], '15.00');
    });

    test('generates valid Base64 string from TLV', () {
      final base64Qr = ZatcaQrService.generateBase64Qr(
        sellerName: 'Fihrist Store',
        vatRegistrationNumber: '300123456700003',
        timestamp: testDate,
        invoiceTotalWithVat: '230.00',
        vatTotal: '30.00',
      );

      expect(base64Qr, isNotEmpty);

      // Verify it decodes back to valid TLV
      final rawBytes = base64.decode(base64Qr);
      final decoded = ZatcaQrService.decodeTlv(Uint8List.fromList(rawBytes));
      expect(decoded[1], 'Fihrist Store');
      expect(decoded[2], '300123456700003');
      expect(decoded[4], '230.00');
      expect(decoded[5], '30.00');
    });

    test('supports Phase 2 optional tags (Hash, ECDSA signature, Public Key)', () {
      final dummyHash = 'a1b2c3d4e5f678901234567890abcdef1234567890abcdef1234567890abcdef';
      final dummySig = Uint8List.fromList([0x30, 0x45, 0x02, 0x20]);
      final dummyPub = Uint8List.fromList([0x04, 0x12, 0x34, 0x56]);

      final tlvBytes = ZatcaQrService.encodeTlv(
        sellerName: 'فهرست المرحلة الثانية',
        vatRegistrationNumber: '300123456700003',
        timestamp: testDate,
        invoiceTotalWithVat: '500.00',
        vatTotal: '65.22',
        xmlInvoiceHash: dummyHash,
        ecdsaSignature: dummySig,
        ecdsaPublicKey: dummyPub,
      );

      final decoded = ZatcaQrService.decodeTlv(tlvBytes);
      expect(decoded[1], 'فهرست المرحلة الثانية');
      expect(decoded[6], dummyHash);
    });

    test('generates ESC/POS QR printing command sequence', () {
      const qrData = 'AQ1GaWhyaXN0IFN0b3Jl';
      final commands = ZatcaQrService.generateEscPosQrCommands(qrData);

      expect(commands, isNotEmpty);
      // GS ( k header check: 0x1D 0x28 0x6B
      expect(commands[0], 0x1D);
      expect(commands[1], 0x28);
      expect(commands[2], 0x6B);
    });
  });
}
