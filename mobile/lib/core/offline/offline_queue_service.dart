import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';
import '../../data/models/product.dart';
import '../../data/repositories/cashier_repository.dart';
import '../secure_storage/secure_token_store.dart';
import '../sync/durable_operation.dart';
import '../sync/durable_sync_engine.dart';

class QueuedSale {
  final String id;
  final List<Map<String, dynamic>> items;
  final String paymentMethod;
  final String total;
  final DateTime createdAt;
  final String? tenantId;
  final String? idempotencyKey;

  QueuedSale({
    required this.id,
    required this.items,
    required this.paymentMethod,
    required this.total,
    required this.createdAt,
    this.tenantId,
    this.idempotencyKey,
  });

  Map<String, dynamic> toJson() => {
        'id': id,
        'items': items,
        'payment_method': paymentMethod,
        'total': total,
        'created_at': createdAt.toIso8601String(),
        'tenant_id': tenantId,
        'idempotency_key': idempotencyKey,
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
        tenantId: json['tenant_id']?.toString(),
        idempotencyKey: json['idempotency_key']?.toString(),
      );
}

/// OfflineQueueService maintains backward compatibility for existing callers
/// while persisting records durably into the SQLite engine per Section 5 of the Master Plan.
class OfflineQueueService {
  static const String _keyOfflineSales = 'pos_offline_sales_queue';
  final SecureTokenStore _tokenStore = SecureTokenStore();
  final DurableSyncEngine _durableEngine = DurableSyncEngine();

  Future<void> enqueueSale({
    required List<CartItem> items,
    required String paymentMethod,
    required String total,
  }) async {
    final now = DateTime.now();
    final opUuid = 'op_${now.millisecondsSinceEpoch}_${now.microsecond % 1000}';
    final idempotencyKey = 'idem_${now.millisecondsSinceEpoch}_${now.microsecondsSinceEpoch % 100000}';
    final tenantId = (await _tokenStore.getTenantId()) ?? 'unknown_tenant';
    final userId = (await _tokenStore.getUserId()) ?? 'offline_user';
    final deviceId = await _tokenStore.getOrCreateDeviceId();
    final registerId = await _tokenStore.getRegisterId();

    final mappedItems = items
        .map((item) => {
              'product_id': item.product.id,
              'name': item.product.name,
              'quantity': item.quantity,
              'unit_price': item.effectiveUnitPrice,
              'line_total': item.lineTotal,
            })
        .toList();

    // 1. Persist into SQLite durable queue
    final durableOp = DurableOperation(
      operationUuid: opUuid,
      tenantId: tenantId,
      userId: userId,
      deviceId: deviceId,
      registerId: registerId,
      operationType: 'pos_sale',
      payloadSnapshot: {
        'items': mappedItems,
        'payment_method': paymentMethod,
        'total': total,
      },
      idempotencyKey: idempotencyKey,
      createdAt: now,
      status: DurableOperationStatus.pending,
    );
    try {
      await _durableEngine.enqueueOperation(durableOp);
    } catch (_) {
      // In web or tests where native sqlite is mocked, fallback to prefs
    }

    // 2. Also keep in shared preferences for legacy query / fast sync
    final prefs = await SharedPreferences.getInstance();
    final currentList = await getPendingQueue();

    final newSale = QueuedSale(
      id: opUuid,
      paymentMethod: paymentMethod,
      total: total,
      createdAt: now,
      tenantId: tenantId,
      idempotencyKey: idempotencyKey,
      items: mappedItems,
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
              sku: '',
              price: it['unit_price']?.toString() ?? '0.00',
              stockQuantity: 99,
            ),
            quantity: (it['quantity'] as num?)?.toInt() ?? 1,
            customPrice: it['unit_price']?.toString(),
          );
        }).toList();

        final result = await repository.checkout(
          items: mockItems,
          paymentMethod: sale.paymentMethod,
          total: sale.total,
        );

        if (result['success'] == true || result['id'] != null || result['order_id'] != null) {
          syncedCount++;
        } else {
          remaining.add(sale);
        }
      } catch (_) {
        remaining.add(sale);
      }
    }

    final prefs = await SharedPreferences.getInstance();
    final jsonList = remaining.map((s) => s.toJson()).toList();
    await prefs.setString(_keyOfflineSales, jsonEncode(jsonList));

    return syncedCount;
  }

  Future<void> clearQueue() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_keyOfflineSales);
  }
}
