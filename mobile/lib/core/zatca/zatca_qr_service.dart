import 'dart:convert';
import 'dart:typed_data';

/// ZATCA (هيئة الزكاة والضريبة والجمارك) E-Invoicing TLV QR Code Service
/// Implements Phase 1 & Phase 2 Saudi Electronic Invoicing standard (FATOORA).
class ZatcaQrService {
  /// Encodes individual TLV field: [Tag, Length, ...ValueBytes]
  static List<int> _encodeTlvField(int tag, String value) {
    final valueBytes = utf8.encode(value);
    if (valueBytes.length > 255) {
      throw ArgumentError('ZATCA TLV value exceeds 255 bytes for tag $tag');
    }
    return [tag, valueBytes.length, ...valueBytes];
  }

  /// Encodes raw bytes TLV field (for Hash, ECDSA signature, and Public Key)
  static List<int> _encodeTlvBytesField(int tag, Uint8List valueBytes) {
    if (valueBytes.length > 255) {
      throw ArgumentError('ZATCA TLV bytes exceed 255 bytes for tag $tag');
    }
    return [tag, valueBytes.length, ...valueBytes];
  }

  /// Generates standard ZATCA TLV byte buffer
  static Uint8List encodeTlv({
    required String sellerName,
    required String vatRegistrationNumber,
    required DateTime timestamp,
    required String invoiceTotalWithVat,
    required String vatTotal,
    String? xmlInvoiceHash,
    Uint8List? ecdsaSignature,
    Uint8List? ecdsaPublicKey,
  }) {
    final bytes = <int>[];

    // Tag 1: Seller's name
    bytes.addAll(_encodeTlvField(1, sellerName));

    // Tag 2: VAT registration number
    bytes.addAll(_encodeTlvField(2, vatRegistrationNumber));

    // Tag 3: Timestamp (ISO 8601: YYYY-MM-DDTHH:mm:ssZ)
    final isoTimestamp = '${timestamp.toUtc().toIso8601String().split('.').first}Z';
    bytes.addAll(_encodeTlvField(3, isoTimestamp));

    // Tag 4: Invoice total (with VAT)
    bytes.addAll(_encodeTlvField(4, invoiceTotalWithVat));

    // Tag 5: Total VAT
    bytes.addAll(_encodeTlvField(5, vatTotal));

    // Phase 2 Optional Tags:
    // Tag 6: SHA-256 Hash of XML invoice
    if (xmlInvoiceHash != null && xmlInvoiceHash.isNotEmpty) {
      bytes.addAll(_encodeTlvField(6, xmlInvoiceHash));
    }

    // Tag 7: ECDSA Digital Signature (Cryptographic Stamp)
    if (ecdsaSignature != null && ecdsaSignature.isNotEmpty) {
      bytes.addAll(_encodeTlvBytesField(7, ecdsaSignature));
    }

    // Tag 8: ECDSA Public Key
    if (ecdsaPublicKey != null && ecdsaPublicKey.isNotEmpty) {
      bytes.addAll(_encodeTlvBytesField(8, ecdsaPublicKey));
    }

    return Uint8List.fromList(bytes);
  }

  /// Generates the standard Base64 QR payload required by ZATCA
  static String generateBase64Qr({
    required String sellerName,
    required String vatRegistrationNumber,
    required DateTime timestamp,
    required String invoiceTotalWithVat,
    required String vatTotal,
    String? xmlInvoiceHash,
    Uint8List? ecdsaSignature,
    Uint8List? ecdsaPublicKey,
  }) {
    final tlvBytes = encodeTlv(
      sellerName: sellerName,
      vatRegistrationNumber: vatRegistrationNumber,
      timestamp: timestamp,
      invoiceTotalWithVat: invoiceTotalWithVat,
      vatTotal: vatTotal,
      xmlInvoiceHash: xmlInvoiceHash,
      ecdsaSignature: ecdsaSignature,
      ecdsaPublicKey: ecdsaPublicKey,
    );
    return base64.encode(tlvBytes);
  }

  /// Decodes a TLV byte buffer back into map of tags (for verification & compliance testing)
  static Map<int, String> decodeTlv(Uint8List tlvBytes) {
    final result = <int, String>{};
    int index = 0;

    while (index < tlvBytes.length) {
      if (index + 2 > tlvBytes.length) break;
      final tag = tlvBytes[index];
      final length = tlvBytes[index + 1];
      index += 2;

      if (index + length > tlvBytes.length) break;
      final valueBytes = tlvBytes.sublist(index, index + length);
      result[tag] = utf8.decode(valueBytes, allowMalformed: true);
      index += length;
    }

    return result;
  }

  /// Generates standard ESC/POS QR Code printing command sequence
  /// Standard ESC/POS: GS ( k ...
  static List<int> generateEscPosQrCommands(String qrData) {
    final dataBytes = utf8.encode(qrData);
    final commands = <int>[];

    // GS ( k pL pH cn fn n (Select QR model 2)
    // 0x1D 0x28 0x6B 0x04 0x00 0x31 0x41 0x32 0x00
    commands.addAll([0x1D, 0x28, 0x6B, 0x04, 0x00, 0x31, 0x41, 0x32, 0x00]);

    // GS ( k pL pH cn fn n (Set module size: 4 dots per module)
    // 0x1D 0x28 0x6B 0x03 0x00 0x31 0x43 0x04
    commands.addAll([0x1D, 0x28, 0x6B, 0x03, 0x00, 0x31, 0x43, 0x04]);

    // GS ( k pL pH cn fn n (Set error correction level: M ~15%)
    // 0x1D 0x28 0x6B 0x03 0x00 0x31 0x45 0x31
    commands.addAll([0x1D, 0x28, 0x6B, 0x03, 0x00, 0x31, 0x45, 0x31]);

    // GS ( k pL pH cn fn m d1...dk (Store QR data)
    final storeLen = dataBytes.length + 3;
    final pL = storeLen & 0xFF;
    final pH = (storeLen >> 8) & 0xFF;
    commands.addAll([0x1D, 0x28, 0x6B, pL, pH, 0x31, 0x50, 0x30]);
    commands.addAll(dataBytes);

    // GS ( k pL pH cn fn m (Print QR code)
    // 0x1D 0x28 0x6B 0x03 0x00 0x31 0x51 0x30
    commands.addAll([0x1D, 0x28, 0x6B, 0x03, 0x00, 0x31, 0x51, 0x30]);

    return commands;
  }
}
