/// AGENTS.md rule: Money is a string on the wire (never float).
/// Monetary calculations and display must never convert to IEEE-754 double/float
/// to prevent floating-point rounding errors.
class MoneyFormatter {
  /// Formats an exact money string (e.g. "125.50" or "100") into a localized display
  /// e.g. "125.50 ر.س" or "125.50 SAR"
  static String format(String? amount, {String currency = 'ر.س'}) {
    if (amount == null || amount.trim().isEmpty) {
      return '0.00 $currency';
    }

    final trimmed = amount.trim();
    final parts = trimmed.split('.');
    final integerPart = parts[0].isEmpty ? '0' : parts[0];
    String fractionPart = parts.length > 1 ? parts[1] : '00';

    if (fractionPart.length == 1) {
      fractionPart = '${fractionPart}0';
    } else if (fractionPart.length > 2) {
      fractionPart = fractionPart.substring(0, 2);
    }

    // Add thousands separators
    final formattedInt = _addThousandsSeparators(integerPart);
    return '$formattedInt.$fractionPart $currency';
  }

  /// Adds two exact money strings (e.g. "10.50" + "20.25" = "30.75") using integer cents
  static String add(String a, String b) {
    final centsA = toCents(a);
    final centsB = toCents(b);
    final totalCents = centsA + centsB;
    return fromCents(totalCents);
  }

  /// Multiplies a money string by an integer quantity
  static String multiply(String unitPrice, int quantity) {
    final cents = toCents(unitPrice);
    final totalCents = cents * BigInt.from(quantity);
    return fromCents(totalCents);
  }

  /// Converts a money string "12.34" to BigInt cents (1234)
  static BigInt toCents(String amount) {
    final trimmed = amount.trim();
    if (trimmed.isEmpty) return BigInt.zero;

    final isNegative = trimmed.startsWith('-');
    final clean = isNegative ? trimmed.substring(1) : trimmed;
    final parts = clean.split('.');

    final whole = parts[0].isEmpty ? '0' : parts[0];
    String fraction = parts.length > 1 ? parts[1] : '00';

    if (fraction.length == 1) {
      fraction = '${fraction}0';
    } else if (fraction.length > 2) {
      fraction = fraction.substring(0, 2);
    }

    final wholeBig = BigInt.tryParse(whole) ?? BigInt.zero;
    final fractionBig = BigInt.tryParse(fraction) ?? BigInt.zero;

    final cents = (wholeBig * BigInt.from(100)) + fractionBig;
    return isNegative ? -cents : cents;
  }

  /// Converts BigInt cents (1234) back to exact money string "12.34"
  static String fromCents(BigInt cents) {
    final isNegative = cents < BigInt.zero;
    final abs = isNegative ? -cents : cents;

    final whole = abs ~/ BigInt.from(100);
    final fraction = abs % BigInt.from(100);

    final fractionStr = fraction.toString().padLeft(2, '0');
    final prefix = isNegative ? '-' : '';
    return '$prefix$whole.$fractionStr';
  }

  static String _addThousandsSeparators(String value) {
    final isNegative = value.startsWith('-');
    final digits = isNegative ? value.substring(1) : value;

    final buffer = StringBuffer();
    for (int i = 0; i < digits.length; i++) {
      if (i > 0 && (digits.length - i) % 3 == 0) {
        buffer.write(',');
      }
      buffer.write(digits[i]);
    }

    return (isNegative ? '-' : '') + buffer.toString();
  }
}
