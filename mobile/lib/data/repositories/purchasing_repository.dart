import '../../core/api/api_client.dart';
import '../../core/api/api_endpoints.dart';
import '../../core/secure_storage/secure_token_store.dart';
import '../../core/sync/durable_operation.dart';
import '../../core/sync/durable_sync_engine.dart';
import '../models/purchase_order.dart';

class PurchasingRepository {
  final ApiClient _apiClient;
  final SecureTokenStore _tokenStore;
  final DurableSyncEngine _syncEngine;

  PurchasingRepository({
    ApiClient? apiClient,
    SecureTokenStore? tokenStore,
    DurableSyncEngine? syncEngine,
  })  : _apiClient = apiClient ?? ApiClient(),
        _tokenStore = tokenStore ?? SecureTokenStore(),
        _syncEngine = syncEngine ?? DurableSyncEngine();

  // In-memory fallback dataset consistent with Desktop Purchasing
  final List<Supplier> _mockSuppliers = [
    const Supplier(
      id: 's1',
      name: 'شركة نسيج الجزيرة للأقمشة والملابس',
      phone: '0501122334',
      contactPerson: 'سلمان العتيبي',
      balanceSar: '12400.00',
    ),
    const Supplier(
      id: 's2',
      name: 'مؤسسة الرياض للأحذية والمصنوعات الجلدية',
      phone: '0559988776',
      contactPerson: 'فهد القحطاني',
      balanceSar: '6800.00',
    ),
    const Supplier(
      id: 's3',
      name: 'شركة أطياب الشرق للعطور والزيوت',
      phone: '0543322110',
      contactPerson: 'بندر الشمري',
      balanceSar: '0.00',
    ),
  ];

  final List<PurchaseOrder> _mockOrders = [
    const PurchaseOrder(
      id: 'po1',
      poNumber: 'PO-2026-001',
      supplierId: 's1',
      supplierName: 'شركة نسيج الجزيرة للأقمشة والملابس',
      orderDate: '2026-11-18',
      totalSar: '18500.00',
      status: PurchaseOrderStatus.received,
      items: [
        PurchaseOrderItem(
          productId: 'i1',
          productName: 'قميص أكسفورد كلاسيك أبيض',
          quantity: 100,
          unitCost: '90.00',
          receivedQuantity: 100,
        ),
        PurchaseOrderItem(
          productId: 'i3',
          productName: 'تي شيرت قطن مصري أسود',
          quantity: 200,
          unitCost: '45.00',
          receivedQuantity: 200,
        ),
      ],
    ),
    const PurchaseOrder(
      id: 'po2',
      poNumber: 'PO-2026-002',
      supplierId: 's2',
      supplierName: 'مؤسسة الرياض للأحذية والمصنوعات الجلدية',
      orderDate: '2026-11-20',
      totalSar: '6800.00',
      status: PurchaseOrderStatus.pending,
      items: [
        PurchaseOrderItem(
          productId: 'i4',
          productName: 'حذاء كاجوال جلد بني',
          quantity: 40,
          unitCost: '170.00',
          receivedQuantity: 0,
        ),
      ],
    ),
  ];

  Future<List<Supplier>> getSuppliers() async {
    try {
      final res = await _apiClient.get('/api/v1/purchasing/suppliers');
      if (res is List<dynamic>) {
        return res.map((json) => Supplier.fromJson(json as Map<String, dynamic>)).toList();
      }
    } catch (_) {
      // Fallback to cache/mock
    }
    return _mockSuppliers;
  }

  Future<List<PurchaseOrder>> getPurchaseOrders() async {
    try {
      final res = await _apiClient.get(ApiEndpoints.purchaseOrders);
      if (res is List<dynamic>) {
        return res.map((json) => PurchaseOrder.fromJson(json as Map<String, dynamic>)).toList();
      }
    } catch (_) {
      // Fallback
    }
    return _mockOrders;
  }

  Future<bool> receiveShipment({
    required String orderId,
    required Map<String, int> receivedQuantities,
    String? inspectionNotes,
  }) async {
    final idx = _mockOrders.indexWhere((o) => o.id == orderId);
    if (idx != -1) {
      final existing = _mockOrders[idx];
      final updatedItems = existing.items.map((item) {
        final qty = receivedQuantities[item.productId] ?? item.quantity;
        return item.copyWith(receivedQuantity: qty);
      }).toList();

      _mockOrders[idx] = existing.copyWith(
        status: PurchaseOrderStatus.received,
        items: updatedItems,
        notes: inspectionNotes,
      );
    }

    String tenantId = 'unknown_tenant';
    String userId = 'unknown_user';
    try {
      tenantId = (await _tokenStore.getTenantId()) ?? 'unknown_tenant';
      userId = (await _tokenStore.getUserId()) ?? 'unknown_user';
    } catch (_) {
      // Safe fallback in test environment
    }

    final opUuid = 'recv_${DateTime.now().millisecondsSinceEpoch}_$orderId';
    final payload = {
      'order_id': orderId,
      'received_items': receivedQuantities,
      'inspection_notes': inspectionNotes,
      'timestamp': DateTime.now().toIso8601String(),
    };

    bool sentOnline = false;
    try {
      final response = await _apiClient.post(
        ApiEndpoints.purchaseOrderReceive(orderId),
        body: payload,
      );
      if (response != null) {
        sentOnline = true;
      }
    } catch (_) {
      sentOnline = false;
    }

    if (!sentOnline) {
      try {
        final op = DurableOperation(
          operationUuid: opUuid,
          tenantId: tenantId,
          userId: userId,
          deviceId: 'mobile_device',
          operationType: 'receive_purchase_order',
          payloadSnapshot: payload,
          idempotencyKey: opUuid,
          status: DurableOperationStatus.pending,
          createdAt: DateTime.now(),
        );
        await _syncEngine.enqueueOperation(op);
      } catch (_) {
        // Safe fallback in test environment
      }
    }

    return true;
  }
}
