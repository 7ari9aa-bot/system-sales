import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:fihrist_mobile/core/offline/offline_queue_service.dart';
import 'package:fihrist_mobile/data/models/product.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('OfflineQueueService', () {
    setUp(() {
      SharedPreferences.setMockInitialValues({});
    });

    test('enqueues sales offline and retrieves pending queue accurately', () async {
      final queueService = OfflineQueueService();
      final initialQueue = await queueService.getPendingQueue();
      expect(initialQueue, isEmpty);

      final dummyProduct = Product(
        id: 'prod-1',
        name: 'قهوة سعودية',
        price: '25.00',
        stockQuantity: 50,
      );

      final items = [
        CartItem(product: dummyProduct, quantity: 2),
      ];

      await queueService.enqueueSale(
        items: items,
        paymentMethod: 'cash',
        total: '57.50',
      );

      final pending = await queueService.getPendingQueue();
      expect(pending.length, 1);
      expect(pending.first.paymentMethod, 'cash');
      expect(pending.first.total, '57.50');
      expect(pending.first.items.length, 1);
      expect(pending.first.items.first['product_id'], 'prod-1');
      expect(pending.first.items.first['quantity'], 2);
    });
  });
}
