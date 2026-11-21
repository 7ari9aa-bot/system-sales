import 'package:flutter_test/flutter_test.dart';
import 'package:fihrist_mobile/core/utils/money_formatter.dart';

void main() {
  group('MoneyFormatter (AGENTS.md rule)', () {
    test('format handles null and empty safely', () {
      expect(MoneyFormatter.format(null), '0.00 ر.س');
      expect(MoneyFormatter.format(''), '0.00 ر.س');
    });

    test('format adds currency and handles single/double decimal places', () {
      expect(MoneyFormatter.format('10'), '10.00 ر.س');
      expect(MoneyFormatter.format('10.5'), '10.50 ر.س');
      expect(MoneyFormatter.format('10.50'), '10.50 ر.س');
      expect(MoneyFormatter.format('1234.56', currency: 'SAR'), '1,234.56 SAR');
    });

    test('add avoids IEEE-754 floating point imprecision (e.g. 0.1 + 0.2)', () {
      // 0.1 + 0.2 in floating point is 0.30000000000000004
      // In MoneyFormatter, it must be exact: "0.30"
      final sum = MoneyFormatter.add('0.10', '0.20');
      expect(sum, '0.30');
    });

    test('multiply calculates exact price * quantity without float errors', () {
      // "35.50" * 3 = "106.50"
      final result = MoneyFormatter.multiply('35.50', 3);
      expect(result, '106.50');
    });

    test('toCents and fromCents work accurately', () {
      expect(MoneyFormatter.toCents('125.75'), BigInt.from(12575));
      expect(MoneyFormatter.fromCents(BigInt.from(12575)), '125.75');
    });
  });
}
