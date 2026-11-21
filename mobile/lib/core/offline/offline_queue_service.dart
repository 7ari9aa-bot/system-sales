import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';
import '../../data/models/product.dart';
import '../../data/repositories/cashier_repository.dart';

class QueuedSale {
  final String id;
  final List<Map<String, dynamic>> items;
  final String paymentMethod;
  final String total;
  final DateTime createdAt;

  QueuedSale({
    required this.id,
    required this.items,
    required this.paymentMethod,
    required this.total,
    required this.createdAt,
  });

  Map<String, dynamic> toJson() => {
        'id': id,
        'items': items,
        'payment_method': paymentMethod,
        'total': total,
        'created_at': createdAt.toIso8601String(),
      };

  factory QueuedSale.fromJson(Map<String, dynamic> json) => QueuedSale(
        id: json['id']?.toString() ?? '',
        items: (json['items'] as List<dynamic>?)
                ?.map((e) => Map<String, dynamic>.from(e as Map))
                .toList() ??
            [],
        paymentMethod: json['payment_method']?.toString() ?? 'cash',
        total: json['total']?.toString() ?? '0.00',
        createdAt: json['created_at'] != null
            ? DateTime.tryParse(json['created_at'].toString()) ?? DateTime.now()
            : DateTime.now(),
      );
}

class OfflineQueueService {
  static const String _keyOfflineSales = 'pos_offline_sales_queue';

  Future<void> enqueueSale({
    required List<CartItem> items,
    required String paymentMethod,
    required String total,
  }) async {
    final prefs = await SharedPreferences.getInstance();
    final currentList = await getPendingQueue();

    final newSale = QueuedSale(
      id: 'offline_${DateTime.now().millisecondsSinceEpoch}',
      paymentMethod: paymentMethod,
      total: total,
      createdAt: DateTime.now(),
      items: items
          .map((item) => {
                'product_id': item.product.id,
                'name': item.product.name,
                'quantity': item.quantity,
                'unit_price': item.effectiveUnitPrice,
                'line_total': item.lineTotal,
              })
          .toList(),
    );

    currentList.add(newSale);
    final jsonList = currentList.map((s) => s.toJson()).toList();
    await prefs.setString(_keyOfflineSales, jsonEncode(jsonList));
  }

  Future<List<QueuedSale>> getPendingQueue() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_keyOfflineSales);
    if (raw == null || raw.isEmpty) return [];

    try {
      final decoded = jsonDecode(raw) as List<dynamic>;
      return decoded
          .map((item) => QueuedSale.fromJson(item as Map<String, dynamic>))
          .toList();
    } catch (_) {
      return [];
    }
  }

  Future<int> syncPendingQueue(CashierRepository repository) async {
    final queue = await getPendingQueue();
    if (queue.isEmpty) return 0;

    int syncedCount = 0;
    final remaining = <QueuedSale>[];

    for (final sale in queue) {
      try {
        final mockItems = sale.items.map((it) {
          return CartItem(
            product: Product(
              id: it['product_id']?.toString() ?? '',
              name: it['name']?.toString() ?? '',
              price: it['unit_price']?.toString() ?? '0.00',
            ),
            quantity: (it['quantity'] as num?)?.toInt() ?? 1,
          );
        }).toList();

        await repository.checkout(
          items: mockItems,
          paymentMethod: sale.paymentMethod,
          total: sale.total,
        );
        syncedCount++;
      } catch (_) {
        remaining.add(sale);
      }
    }

    final prefs = await SharedPreferences.getInstance();
    if (remaining.isEmpty) {
      await prefs.remove(_keyOfflineSales);
    } else {
      await prefs.setString(
        _keyOfflineSales,
        jsonEncode(remaining.map((s) => s.toJson()).toList()),
      );
    }

    return syncedCount;
  }

  Future<void> clearQueue() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_keyOfflineSales);
  }
}
