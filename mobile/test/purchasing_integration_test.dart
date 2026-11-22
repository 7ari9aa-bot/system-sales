import 'package:flutter_test/flutter_test.dart';
import 'package:fihrist_mobile/data/models/purchase_order.dart';
import 'package:fihrist_mobile/data/repositories/purchasing_repository.dart';
import 'package:fihrist_mobile/providers/purchasing_view_model.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('Purchasing & Receiving Integration Tests', () {
    late PurchasingRepository repository;
    late PurchasingViewModel viewModel;

    setUp(() {
      repository = PurchasingRepository();
      viewModel = PurchasingViewModel(repository: repository);
    });

    test('loads suppliers and purchase orders successfully', () async {
      await viewModel.loadPurchasingData();

      expect(viewModel.suppliers.isNotEmpty, isTrue);
      expect(viewModel.orders.isNotEmpty, isTrue);

      final firstSupplier = viewModel.suppliers.first;
      expect(firstSupplier.name, contains('نسيج الجزيرة'));
      expect(firstSupplier.balanceSar, equals('12400.00'));

      final pendingOrders = viewModel.pendingOrders;
      expect(pendingOrders.any((o) => o.poNumber == 'PO-2026-002'), isTrue);
    });

    test('receives shipment and updates status to received', () async {
      await viewModel.loadPurchasingData();

      const orderId = 'po2';
      final receivedQuantities = {'i4': 40};
      final ok = await viewModel.receiveShipment(
        orderId: orderId,
        receivedQuantities: receivedQuantities,
        inspectionNotes: 'تم فحص جميع البنود سليمة',
      );

      expect(ok, isTrue);

      final updatedOrder = viewModel.orders.firstWhere((o) => o.id == orderId);
      expect(updatedOrder.status, equals(PurchaseOrderStatus.received));
      expect(updatedOrder.notes, equals('تم فحص جميع البنود سليمة'));
      expect(updatedOrder.items.first.receivedQuantity, equals(40));
    });

    test('PurchaseOrder JSON serialization is accurate', () {
      const order = PurchaseOrder(
        id: 'test_po',
        poNumber: 'PO-TEST-01',
        supplierId: 's1',
        supplierName: 'مورد تجريبي',
        orderDate: '2026-11-22',
        totalSar: '500.00',
        status: PurchaseOrderStatus.pending,
        items: [
          PurchaseOrderItem(
            productId: 'p1',
            productName: 'منتج أ',
            quantity: 5,
            unitCost: '100.00',
            receivedQuantity: 0,
          ),
        ],
      );

      final json = order.toJson();
      final fromJson = PurchaseOrder.fromJson(json);

      expect(fromJson.id, equals('test_po'));
      expect(fromJson.poNumber, equals('PO-TEST-01'));
      expect(fromJson.status, equals(PurchaseOrderStatus.pending));
      expect(fromJson.items.length, equals(1));
      expect(fromJson.items.first.quantity, equals(5));
    });
  });
}
