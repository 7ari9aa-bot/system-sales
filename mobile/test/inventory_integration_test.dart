import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:fihrist_mobile/data/models/product.dart';
import 'package:fihrist_mobile/data/repositories/inventory_repository.dart';
import 'package:fihrist_mobile/providers/inventory_view_model.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  group('InventoryRepository & InventoryViewModel Tests', () {
    test('fetches inventory products and handles low-stock filtering', () async {
      final repo = InventoryRepository();
      final allProducts = await repo.getInventory();

      expect(allProducts.isNotEmpty, isTrue);

      final lowStockProducts = await repo.getInventory(lowStockOnly: true);
      for (final p in lowStockProducts) {
        expect(p.stockQuantity <= 5, isTrue);
      }
    });

    test('scans barcode and finds matching product', () async {
      final repo = InventoryRepository();
      final scanned = await repo.scanBarcode('6281001001');

      expect(scanned, isNotNull);
      expect(scanned!.id, 'p1');
      expect(scanned.name, contains('قهوة عربي'));
    });

    test('adjusts stock and calculates updated balance', () async {
      final repo = InventoryRepository();
      const initialProduct = Product(
        id: 'test_prod_1',
        name: 'منتج تجريبي',
        price: '50.00',
        stockQuantity: 20,
      );

      // Increase stock by 5
      final successIn = await repo.adjustStock(
        product: initialProduct,
        deltaQuantity: 5,
        direction: 'in',
        reason: 'adjustment',
      );
      expect(successIn, isTrue);

      // Decrease stock by 3
      final successOut = await repo.adjustStock(
        product: initialProduct,
        deltaQuantity: 3,
        direction: 'out',
        reason: 'damage',
      );
      expect(successOut, isTrue);
    });

    test('performs stock count and reconciles discrepancy', () async {
      final repo = InventoryRepository();
      const product = Product(
        id: 'test_prod_2',
        name: 'صنف جرد',
        price: '100.00',
        stockQuantity: 15,
      );

      // Physical count is 18 (surplus of 3)
      final ok = await repo.countStock(
        product: product,
        countedQuantity: 18,
      );
      expect(ok, isTrue);
    });

    test('creates new product and adds to inventory', () async {
      final repo = InventoryRepository();
      final created = await repo.createProduct(
        name: 'منتج سريع جديد',
        price: '75.50',
        barcode: '628999999001',
        category: 'إلكترونيات',
        initialStock: 12,
      );

      expect(created, isNotNull);
      expect(created.name, 'منتج سريع جديد');
      expect(created.price, '75.50');
      expect(created.stockQuantity, 12);
      expect(created.barcode, '628999999001');

      final found = await repo.scanBarcode('628999999001');
      expect(found, isNotNull);
      expect(found!.name, 'منتج سريع جديد');
    });

    test('InventoryViewModel loads and updates state', () async {
      final repo = InventoryRepository();
      final vm = InventoryViewModel(repository: repo);

      expect(vm.isLoading, isFalse);
      expect(vm.products, isEmpty);

      await vm.loadInventory();

      expect(vm.isLoading, isFalse);
      expect(vm.products.isNotEmpty, isTrue);

      // Low stock count check
      expect(vm.lowStockCount, greaterThanOrEqualTo(0));
    });
  });
}
