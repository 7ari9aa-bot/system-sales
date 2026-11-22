import 'package:flutter/foundation.dart';
import '../data/models/purchase_order.dart';
import '../data/repositories/purchasing_repository.dart';

class PurchasingViewModel extends ChangeNotifier {
  final PurchasingRepository _repository;

  PurchasingViewModel({PurchasingRepository? repository})
      : _repository = repository ?? PurchasingRepository();

  List<Supplier> _suppliers = [];
  List<PurchaseOrder> _orders = [];
  bool _isLoading = false;
  String? _errorMessage;

  List<Supplier> get suppliers => _suppliers;
  List<PurchaseOrder> get orders => _orders;
  bool get isLoading => _isLoading;
  String? get errorMessage => _errorMessage;

  List<PurchaseOrder> get pendingOrders =>
      _orders.where((o) => o.status == PurchaseOrderStatus.pending).toList();

  List<PurchaseOrder> get receivedOrders =>
      _orders.where((o) => o.status == PurchaseOrderStatus.received).toList();

  Future<void> loadPurchasingData() async {
    _isLoading = true;
    _errorMessage = null;
    notifyListeners();

    try {
      final results = await Future.wait([
        _repository.getSuppliers(),
        _repository.getPurchaseOrders(),
      ]);
      _suppliers = results[0] as List<Supplier>;
      _orders = results[1] as List<PurchaseOrder>;
    } catch (e) {
      _errorMessage = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<bool> receiveShipment({
    required String orderId,
    required Map<String, int> receivedQuantities,
    String? inspectionNotes,
  }) async {
    _isLoading = true;
    notifyListeners();

    try {
      final ok = await _repository.receiveShipment(
        orderId: orderId,
        receivedQuantities: receivedQuantities,
        inspectionNotes: inspectionNotes,
      );
      if (ok) {
        await loadPurchasingData();
      }
      return ok;
    } catch (e) {
      _errorMessage = e.toString();
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }
}
