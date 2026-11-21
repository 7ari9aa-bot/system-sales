import 'package:sqflite/sqflite.dart';
import '../../core/api/api_client.dart';
import '../../core/api/api_endpoints.dart';
import '../../core/database/local_database.dart';
import '../../core/secure_storage/secure_token_store.dart';
import '../../core/sync/durable_operation.dart';
import '../../core/sync/durable_sync_engine.dart';
import '../models/product.dart';

class InventoryRepository {
  InventoryRepository({
    ApiClient? apiClient,
    LocalDatabase? localDb,
    SecureTokenStore? tokenStore,
    DurableSyncEngine? syncEngine,
  })  : _apiClient = apiClient ?? ApiClient(),
        _localDb = localDb ?? LocalDatabase.instance,
        _tokenStore = tokenStore ?? SecureTokenStore(),
        _syncEngine = syncEngine ?? DurableSyncEngine();

  final ApiClient _apiClient;
  final LocalDatabase _localDb;
  final SecureTokenStore _tokenStore;
  final DurableSyncEngine _syncEngine;

  static final List<Product> _mockInventory = [
    const Product(
      id: 'p1',
      name: 'قهوة عربي فاخرة 250جم',
      barcode: '6281001001',
      sku: 'COF-ARB-250',
      price: '35.00',
      costPrice: '18.00',
      stockQuantity: 42,
      category: 'مشروبات',
    ),
    const Product(
      id: 'p2',
      name: 'تمر سكري ملكي 1كجم',
      barcode: '6281001002',
      sku: 'DATE-SKR-1K',
      price: '65.00',
      costPrice: '35.00',
      stockQuantity: 4, // Low stock
      category: 'تمور',
    ),
    const Product(
      id: 'p3',
      name: 'هيل أمريكي جامبو 100جم',
      barcode: '6281001003',
      sku: 'CARD-AMR-100',
      price: '48.00',
      costPrice: '26.00',
      stockQuantity: 25,
      category: 'بهارات',
    ),
    const Product(
      id: 'p4',
      name: 'زعفران سوبر نقيل 5جم',
      barcode: '6281001004',
      sku: 'SAFR-NQL-5G',
      price: '120.00',
      costPrice: '75.00',
      stockQuantity: 2, // Low stock
      category: 'بهارات',
    ),
    const Product(
      id: 'p5',
      name: 'شاي تلقيمة فاخر 400جم',
      barcode: '6281001005',
      sku: 'TEA-TLQ-400',
      price: '28.00',
      costPrice: '14.00',
      stockQuantity: 0, // Out of stock
      category: 'مشروبات',
    ),
  ];

  Future<List<Product>> getInventory({String? query, bool? lowStockOnly}) async {
    final q = query?.trim().toLowerCase() ?? '';

    // 1. Fetch live stock from backend
    try {
      final response = await _apiClient.get(
        ApiEndpoints.posStock,
        queryParams: q.isNotEmpty ? {'search': q} : null,
      );

      if (response is List && response.isNotEmpty) {
        final products = response
            .map((item) => Product.fromJson(item as Map<String, dynamic>))
            .toList();

        // Cache into local database
        for (final p in products) {
          await _cacheProduct(p);
        }

        if (lowStockOnly == true) {
          return products.where((p) => p.stockQuantity <= 5).toList();
        }
        return products;
      }
    } catch (_) {}

    // 2. Query local SQLite database
    try {
      final db = await _localDb.database;
      final tenantId = (await _tokenStore.getTenantId()) ?? 'unknown_tenant';

      String where = 'tenant_id = ?';
      final whereArgs = <dynamic>[tenantId];

      if (q.isNotEmpty) {
        where += ' AND (name LIKE ? OR barcode = ? OR sku = ?)';
        whereArgs.addAll(['%$q%', q, q]);
      }
      if (lowStockOnly == true) {
        where += ' AND stock_quantity <= 5';
      }

      final rows = await db.query(
        'cached_products',
        where: where,
        whereArgs: whereArgs,
        limit: 100,
      );

      if (rows.isNotEmpty) {
        return rows
            .map((r) => Product(
                  id: r['id']?.toString() ?? '',
                  name: r['name']?.toString() ?? '',
                  sku: r['sku']?.toString(),
                  barcode: r['barcode']?.toString(),
                  price: r['price']?.toString() ?? '0.00',
                  costPrice: r['cost_price']?.toString(),
                  category: r['category']?.toString(),
                  stockQuantity: (r['stock_quantity'] as num?)?.toInt() ?? 0,
                ))
            .toList();
      }
    } catch (_) {}

    // 3. Fallback mock products
    return _mockInventory.where((p) {
      if (lowStockOnly == true && p.stockQuantity > 5) return false;
      if (q.isEmpty) return true;
      return p.name.toLowerCase().contains(q) ||
          (p.barcode != null && p.barcode!.contains(q)) ||
          (p.sku != null && p.sku!.toLowerCase().contains(q));
    }).toList();
  }

  Future<Product?> scanBarcode(String barcode) async {
    final cleaned = barcode.trim();
    if (cleaned.isEmpty) return null;

    final results = await getInventory(query: cleaned);
    if (results.isNotEmpty) {
      return results.firstWhere(
        (p) => p.barcode == cleaned || p.sku == cleaned,
        orElse: () => results.first,
      );
    }
    return null;
  }

  /// Adjust stock for a variant (direction: 'in' | 'out', reason: 'adjustment' | 'damage' | 'stocktake')
  Future<bool> adjustStock({
    required Product product,
    required int deltaQuantity,
    required String direction, // 'in' or 'out'
    String reason = 'adjustment',
    String? warehouseId,
  }) async {
    if (deltaQuantity <= 0) return false;

    final tenantId = (await _tokenStore.getTenantId()) ?? 'unknown_tenant';
    final userId = (await _tokenStore.getUserId()) ?? 'unknown_user';
    final targetWarehouseId = warehouseId ?? '00000000-0000-0000-0000-000000000001';

    final int newStock = direction == 'in'
        ? product.stockQuantity + deltaQuantity
        : (product.stockQuantity - deltaQuantity).clamp(0, 999999);

    final updatedProduct = product.copyWith(stockQuantity: newStock);
    await _cacheProduct(updatedProduct);

    final payload = {
      'variant_id': product.id,
      'warehouse_id': targetWarehouseId,
      'direction': direction,
      'quantity': deltaQuantity,
      'reason': reason,
    };

    final opUuid = 'inv_${DateTime.now().millisecondsSinceEpoch}_${product.id.substring(0, 4)}';
    final idempotencyKey = 'idemp_$opUuid';

    bool sentOnline = false;
    try {
      final response = await _apiClient.post(
        '/api/v1/inventory/movements',
        body: payload,
        extraHeaders: {
          'Idempotency-Key': idempotencyKey,
          'X-Operation-UUID': opUuid,
        },
      );
      if (response != null) {
        sentOnline = true;
      }
    } catch (_) {
      sentOnline = false;
    }

    if (!sentOnline) {
      // Queue offline in durable operations table
      final op = DurableOperation(
        operationUuid: opUuid,
        tenantId: tenantId,
        userId: userId,
        deviceId: 'mobile_device',
        operationType: 'inventory_movement',
        payloadSnapshot: payload,
        idempotencyKey: idempotencyKey,
        status: DurableOperationStatus.pending,
        createdAt: DateTime.now(),
      );
      await _syncEngine.enqueueOperation(op);
    }

    return true;
  }

  /// Perform a stock count reconciliation (calculating in/out delta)
  Future<bool> countStock({
    required Product product,
    required int countedQuantity,
    String? warehouseId,
  }) async {
    final diff = countedQuantity - product.stockQuantity;
    if (diff == 0) return true; // No change needed

    final direction = diff > 0 ? 'in' : 'out';
    final delta = diff.abs();

    return adjustStock(
      product: product,
      deltaQuantity: delta,
      direction: direction,
      reason: 'stocktake',
      warehouseId: warehouseId,
    );
  }

  Future<void> _cacheProduct(Product product) async {
    try {
      final db = await _localDb.database;
      final tenantId = (await _tokenStore.getTenantId()) ?? 'unknown_tenant';
      await db.insert(
        'cached_products',
        {
          'id': product.id,
          'tenant_id': tenantId,
          'name': product.name,
          'sku': product.sku,
          'barcode': product.barcode,
          'price': product.price,
          'cost_price': product.costPrice,
          'stock_quantity': product.stockQuantity,
          'category': product.category,
          'updated_at': DateTime.now().toIso8601String(),
        },
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
    } catch (_) {}
  }
}
