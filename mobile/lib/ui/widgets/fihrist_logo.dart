import 'package:flutter/material.dart';

/// Pixel-perfect vector rendering of the official FIHRIST brand mark.
/// Based directly on `frontend/public/fihrist-mark.svg`.
class FihristBrandMark extends StatelessWidget {
  const FihristBrandMark({
    super.key,
    this.size = 80,
    this.borderRadius,
    this.showShadow = true,
  });

  final double size;
  final double? borderRadius;
  final bool showShadow;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(borderRadius ?? (size * (24 / 120))),
        boxShadow: showShadow
            ? [
                BoxShadow(
                  color: const Color(0xFF0E6B63).withValues(alpha: 0.25),
                  blurRadius: size * 0.2,
                  offset: Offset(0, size * 0.08),
                ),
              ]
            : null,
      ),
      child: CustomPaint(
        size: Size(size, size),
        painter: _FihristLogoPainter(),
      ),
    );
  }
}

class _FihristLogoPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final scale = size.width / 120.0;
    canvas.save();
    canvas.scale(scale, scale);

    // 1. Background rounded rectangle (#0E6B63)
    final bgPaint = Paint()
      ..color = const Color(0xFF0E6B63)
      ..style = PaintingStyle.fill;
    final rrect = RRect.fromRectAndRadius(
      const Rect.fromLTWH(0, 0, 120, 120),
      const Radius.circular(24),
    );
    canvas.drawRRect(rrect, bgPaint);

    // 2. Open pages (#F7F4EE)
    final pagePaint = Paint()
      ..color = const Color(0xFFF7F4EE)
      ..style = PaintingStyle.fill;

    // Left page: M27 28 58 40v54L27 82z
    final leftPage = Path()
      ..moveTo(27, 28)
      ..lineTo(58, 40)
      ..lineTo(58, 94)
      ..lineTo(27, 82)
      ..close();
    canvas.drawPath(leftPage, pagePaint);

    // Right page: M65 40l28-12v54L65 94z
    final rightPage = Path()
      ..moveTo(65, 40)
      ..lineTo(93, 28)
      ..lineTo(93, 82)
      ..lineTo(65, 94)
      ..close();
    canvas.drawPath(rightPage, pagePaint);

    // 3. Center spine divider (#0E6B63): M58 40h7v54h-7z
    final spinePaint = Paint()
      ..color = const Color(0xFF0E6B63)
      ..style = PaintingStyle.fill;
    canvas.drawRect(const Rect.fromLTWH(58, 40, 7, 54), spinePaint);

    // 4. Accent coral/terracotta dot (#D9785B): cx="88" cy="57" r="9"
    final dotPaint = Paint()
      ..color = const Color(0xFFD9785B)
      ..style = PaintingStyle.fill;
    canvas.drawCircle(const Offset(88, 57), 9, dotPaint);

    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
