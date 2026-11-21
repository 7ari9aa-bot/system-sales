import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:fihrist_mobile/core/sync/durable_operation.dart';
import 'package:fihrist_mobile/data/models/product.dart';
import 'package:fihrist_mobile/data/repositories/cashier_repository.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('POS & Catalog Master Plan Integration Tests', () {
    late CashierRepository repository;

    setUp(() {
      SharedPreferences.setMockInitialValues({});
      repository = CashierRepository();
    });

    test('Product.fromJson parses both standard product and OpenAPI StockRow schema', () {
      // 1. Standard format
      final standardJson = {
        'id': 'v_123',
        'name': 'قميص أبيض قطن',
        'barcode': '6281001001',
        'sku': 'SHIRT-WHT-L',
        'price': '185.00',
        'cost_price': '90.00',
        'category': 'ملابس',
        'stock_quantity': 24,
      };

      final p1 = Product.fromJson(standardJson);
      expect(p1.id, 'v_123');
      expect(p1.name, 'قميص أبيض قطن');
      expect(p1.price, '185.00');
      expect(p1.stockQuantity, 24);

      // 2. OpenAPI StockRow format from /api/v1/pos/stock
      final stockRowJson = {
        'variant_id': 'v_456',
        'product_id': 'prod_789',
        'product_title': 'بنطال جينز أزرق',
        'barcode': '6281001002',
        'sku': 'JEAN-BLU-32',
        'price': '240.00',
        'avg_cost': '120.00',
        'on_hand': 15,
        'category': 'جينز',
        'status': 'in_stock',
      };

      final p2 = Product.fromJson(stockRowJson);
      expect(p2.id, 'v_456');
      expect(p2.name, 'بنطال جينز أزرق');
      expect(p2.price, '240.00');
      expect(p2.costPrice, '120.00');
      expect(p2.stockQuantity, 15);
    });

    test('CashierRepository searchProducts returns matching items', () async {
      final results = await repository.searchProducts('قهوة');
      expect(results, isNotEmpty);
      expect(results.first.name, contains('قهوة'));
    });

    test('DurableOperation correctly maps to and from SQLite map representation', () {
      final now = DateTime.now();
      final op = DurableOperation(
        operationUuid: 'op_test_001',
        tenantId: 'tenant_main',
        userId: 'user_cashier_1',
        deviceId: 'pos_terminal_1',
        registerId: 'reg_01',
        operationType: 'pos_sale',
        payloadSnapshot: {
          'items': [
            {'variant_id': 'v_123', 'quantity': 2, 'unit_price': '35.00'}
          ],
          'payment_method': 'cash',
          'total': '70.00',
        },
        idempotencyKey: 'idem_key_xyz_123',
        createdAt: now,
        status: DurableOperationStatus.pending,
      );

      final map = op.toMap();
      expect(map['operation_uuid'], 'op_test_001');
      expect(map['tenant_id'], 'tenant_main');
      expect(map['status'], 'PENDING');
      expect(map['idempotency_key'], 'idem_key_xyz_123');

      final reconstructed = DurableOperation.fromMap(map);
      expect(reconstructed.operationUuid, op.operationUuid);
      expect(reconstructed.tenantId, op.tenantId);
      expect(reconstructed.status, DurableOperationStatus.pending);
      expect(reconstructed.payloadSnapshot['total'], '70.00');
    });

    test('Cashier checkout builds receipt with unique receipt number', () async {
      final items = [
        CartItem(
          product: const Product(
            id: 'v_1',
            name: 'شاي تلقيمة',
            price: '28.00',
            stockQuantity: 50,
          ),
          quantity: 2,
        ),
      ];

      final result = await repository.checkout(
        items: items,
        paymentMethod: 'cash',
        total: '56.00',
      );

      expect(result['receipt_number'], isNotNull);
      expect(result['receipt_number'].toString(), startsWith('POS-'));
    });
  });
}
