import 'package:sqflite/sqflite.dart';
import '../../core/api/api_client.dart';
import '../../core/api/api_endpoints.dart';
import '../../core/database/local_database.dart';
import '../../core/offline/offline_queue_service.dart';
import '../../core/secure_storage/secure_token_store.dart';
import '../../core/sync/durable_operation.dart';
import '../../core/sync/durable_sync_engine.dart';
import '../models/product.dart';

class CashierRepository {
  CashierRepository({
    ApiClient? apiClient,
    LocalDatabase? localDb,
    SecureTokenStore? tokenStore,
  })  : _apiClient = apiClient ?? ApiClient(),
        _localDb = localDb ?? LocalDatabase.instance,
        _tokenStore = tokenStore ?? SecureTokenStore();

  final ApiClient _apiClient;
  final LocalDatabase _localDb;
  final SecureTokenStore _tokenStore;
  String? _activeSessionId;

  String? get activeSessionId => _activeSessionId;

  Future<String> getOrOpenRegister() async {
    final savedId = await _tokenStore.getRegisterId();
    if (savedId != null && savedId.isNotEmpty && savedId != 'reg_default') return savedId;

    try {
      final response = await _apiClient.get(ApiEndpoints.posRegisters);
      if (response is List && response.isNotEmpty) {
        final regId = response[0]['id']?.toString();
        if (regId != null && regId.isNotEmpty) {
          await _tokenStore.setRegisterId(regId);
          return regId;
        }
      }
    } catch (_) {}

    if (savedId != null && savedId.isNotEmpty && savedId != 'reg_default') return savedId;
    return '00000000-0000-0000-0000-000000000001';
  }

  Future<String> getOrOpenSession() async {
    if (_activeSessionId != null && _activeSessionId != 'session_default') {
      return _activeSessionId!;
    }

    final registerId = await getOrOpenRegister();

    // 1. Check working session on register
    try {
      final wsResp = await _apiClient.post(
        ApiEndpoints.posRegisterWorkingSession(registerId),
        body: {},
      );
      if (wsResp is Map<String, dynamic>) {
        if (wsResp['started'] == true && wsResp['session'] != null) {
          final sid = wsResp['session']['id']?.toString();
          if (sid != null && sid.isNotEmpty) {
            _activeSessionId = sid;
            return _activeSessionId!;
          }
        } else {
          // 2. Day not started yet -> open day with 0.00 opening float
          final openResp = await _apiClient.post(
            ApiEndpoints.posRegisterOpen(registerId),
            body: {'opening_float': '0.00'},
          );
          if (openResp is Map<String, dynamic> && openResp['session'] != null) {
            final sid = openResp['session']['id']?.toString();
            if (sid != null && sid.isNotEmpty) {
              _activeSessionId = sid;
              return _activeSessionId!;
            }
          }
        }
      }
    } catch (_) {}

    // 3. Fallback: list open sessions
    try {
      final response = await _apiClient.get(
        ApiEndpoints.posSessions,
        queryParams: {'register_id': registerId, 'status': 'OPEN'},
      );
      if (response is List && response.isNotEmpty) {
        final sid = response[0]['id']?.toString();
        if (sid != null && sid.isNotEmpty) {
          _activeSessionId = sid;
          return _activeSessionId!;
        }
      }
    } catch (_) {}

    return '00000000-0000-0000-0000-000000000002';
  }

  Future<Product?> scanBarcode(String barcode) async {
    final cleaned = barcode.trim();
    if (cleaned.isEmpty) return null;

    // 1. Try server scan endpoint with OpenAPI ScanRequest schema
    try {
      final sessionId = await getOrOpenSession();
      final response = await _apiClient.post(
        ApiEndpoints.posScan(sessionId),
        body: {
          'identifier_type': 'barcode',
          'value': cleaned,
        },
      );

      if (response is Map<String, dynamic>) {
        final productJson = response['product'] ?? response;
        final p = Product.fromJson(productJson as Map<String, dynamic>);
        await _cacheProduct(p);
        return p;
      }
    } catch (_) {}

    // 2. Query local cache / fallback search
    final results = await searchProducts(cleaned);
    if (results.isNotEmpty) {
      return results.first;
    }
    return null;
  }

  Future<List<Product>> searchProducts(String query) async {
    final q = query.trim().toLowerCase();

    // 1. Try server endpoint using 'term' parameter per OpenAPI contract
    try {
      final response = await _apiClient.get(
        ApiEndpoints.posStock,
        queryParams: q.isNotEmpty ? {'term': q} : null,
      );

      if (response is List) {
        final products = response
            .map((item) => Product.fromJson(item as Map<String, dynamic>))
            .toList();

        // Cache in background
        for (final p in products) {
          await _cacheProduct(p);
        }
        return products;
      }
    } catch (_) {}

    // 2. Query local SQLite database
    try {
      final db = await _localDb.database;
      final tenantId = (await _tokenStore.getTenantId()) ?? 'unknown_tenant';
      final rows = await db.query(
        'cached_products',
        where: q.isNotEmpty
            ? 'tenant_id = ? AND (name LIKE ? OR barcode = ? OR sku = ?)'
            : 'tenant_id = ?',
        whereArgs: q.isNotEmpty ? [tenantId, '%$q%', q, q] : [tenantId],
        limit: 50,
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

    // 3. Fallback demo products
    return _mockProducts.where((p) {
      if (q.isEmpty) return true;
      return p.name.toLowerCase().contains(q) ||
          (p.barcode != null && p.barcode!.contains(q)) ||
          (p.sku != null && p.sku!.toLowerCase().contains(q));
    }).toList();
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
    } catch (_) {
      // In web or tests where SQLite native is absent, ignore
    }
  }

  Future<Map<String, dynamic>> checkout({
    required List<CartItem> items,
    required String paymentMethod, // "cash" or "card"
    required String total,
    String? idempotencyKey,
    String? customerId,
    String? customerName,
    String? customerPhone,
  }) async {
    final key = idempotencyKey ??
        'pos_sale_${DateTime.now().millisecondsSinceEpoch}_${DateTime.now().microsecond % 1000}';
    final registerId = await getOrOpenRegister();

    // Build payload matching OpenAPI RecordSaleRequest exactly
    final payload = {
      'items': items
          .map((item) => {
                'variant_id': item.product.id,
                'quantity': item.quantity,
              })
          .toList(),
      'payments': [
        {
          'method': paymentMethod == 'card' ? 'card' : 'cash',
          'amount': total,
        }
      ],
      if (customerId != null) 'customer_id': customerId,
      if (customerName != null) 'customer_name': customerName,
      if (customerPhone != null) 'customer_phone': customerPhone,
    };

    final token = await _tokenStore.getAccessToken();
    if (token != null && token.isNotEmpty) {
      try {
        final response = await _apiClient.post(
          ApiEndpoints.posRegisterSales(registerId),
          body: payload,
          extraHeaders: {
            'Idempotency-Key': key,
          },
        );

        if (response is Map<String, dynamic>) {
          return {
            ...response,
            'success': true,
            'idempotency_key': key,
            'receipt_number': response['receipt_number'] ??
                'POS-${DateTime.now().millisecondsSinceEpoch.toString().substring(6)}',
            'grand_total': response['grand_total'] ?? total,
          };
        }
      } on ApiException catch (e) {
        // Re-throw genuine 4xx client/validation/auth errors (never mask business rejections as offline success)
        if (e.statusCode >= 400 && e.statusCode < 500 && e.statusCode != 408) {
          rethrow;
        }
        // 5xx or 408 falls through to offline queueing
      } catch (_) {
        // Network disconnect, timeout, or socket exception falls through to offline queueing
      }
    }

    // Offline fallback: Persist into DurableSyncEngine with original key
    final tenantId = (await _tokenStore.getTenantId()) ?? 'unknown_tenant';
    final userId = (await _tokenStore.getUserId()) ?? 'offline_user';
    final deviceId = await _tokenStore.getOrCreateDeviceId();

    final durableOp = DurableOperation(
      operationUuid: 'op_${DateTime.now().millisecondsSinceEpoch}',
      tenantId: tenantId,
      userId: userId,
      deviceId: deviceId,
      registerId: registerId,
      operationType: 'pos_sale',
      payloadSnapshot: payload,
      idempotencyKey: key,
      createdAt: DateTime.now(),
      status: DurableOperationStatus.pending,
    );

    final syncEngine = DurableSyncEngine(localDb: _localDb, apiClient: _apiClient);
    await syncEngine.enqueueOperation(durableOp);

    // Keep OfflineQueueService in lockstep
    try {
      final offlineQueue = OfflineQueueService();
      await offlineQueue.enqueueSale(
        items: items,
        paymentMethod: paymentMethod,
        total: total,
      );
    } catch (_) {}

    return {
      'success': true,
      'offline_queued': true,
      'idempotency_key': key,
      'receipt_number': 'POS-OFFLINE-${DateTime.now().millisecondsSinceEpoch.toString().substring(6)}',
      'grand_total': total,
    };
  }

  static final List<Product> _mockProducts = [
    const Product(
      id: 'p1',
      name: 'قهوة عربي فاخرة 250جم',
      barcode: '6281001001',
      price: '35.00',
      stockQuantity: 45,
      category: 'مشروبات',
    ),
    const Product(
      id: 'p2',
      name: 'شاي سيلاني فاخر 100 كيس',
      barcode: '6281001002',
      price: '18.50',
      stockQuantity: 30,
      category: 'مشروبات',
    ),
    const Product(
      id: 'p3',
      name: 'تمر خلاص القصيم 1 كجم',
      barcode: '6281001003',
      price: '45.00',
      stockQuantity: 12,
      category: 'أغذية',
    ),
    const Product(
      id: 'p4',
      name: 'زيت زيتون بكر ممتاز 500 مل',
      barcode: '6281001004',
      price: '28.00',
      stockQuantity: 8,
      category: 'أغذية',
    ),
    const Product(
      id: 'p5',
      name: 'عسل سدر طبيعي 500جم',
      barcode: '6281001005',
      price: '120.00',
      stockQuantity: 5,
      category: 'أغذية',
    ),
  ];
}
