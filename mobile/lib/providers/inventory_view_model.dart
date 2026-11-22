import 'package:flutter/foundation.dart';
import '../core/sync/durable_sync_engine.dart';
import '../data/models/product.dart';
import '../data/repositories/inventory_repository.dart';

class InventoryViewModel extends ChangeNotifier {
  InventoryViewModel({
    InventoryRepository? repository,
    DurableSyncEngine? syncEngine,
  })  : _repository = repository ?? InventoryRepository(),
        _syncEngine = syncEngine ?? DurableSyncEngine();

  final InventoryRepository _repository;
  final DurableSyncEngine _syncEngine;

  List<Product> _products = [];
  bool _isLoading = false;
  String? _errorMessage;
  String _searchQuery = '';
  bool _lowStockOnly = false;
  bool _isSyncing = false;

  List<Product> get products => _products;
  bool get isLoading => _isLoading;
  String? get errorMessage => _errorMessage;
  String get searchQuery => _searchQuery;
  bool get lowStockOnly => _lowStockOnly;
  bool get isSyncing => _isSyncing;

  int get lowStockCount => _products.where((p) => p.stockQuantity <= 5).length;
  int get outOfStockCount => _products.where((p) => p.stockQuantity == 0).length;

  Future<void> loadInventory() async {
    _isLoading = true;
    _errorMessage = null;
    notifyListeners();

    try {
      _products = await _repository.getInventory(
        query: _searchQuery,
        lowStockOnly: _lowStockOnly,
      );
    } catch (e) {
      _errorMessage = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  void setSearchQuery(String query) {
    _searchQuery = query;
    loadInventory();
  }

  void setLowStockOnly(bool value) {
    _lowStockOnly = value;
    loadInventory();
  }

  Future<Product?> scanBarcode(String barcode) async {
    return _repository.scanBarcode(barcode);
  }

  Future<bool> adjustStock({
    required Product product,
    required int deltaQuantity,
    required String direction,
    String reason = 'adjustment',
    String? warehouseId,
  }) async {
    _isLoading = true;
    notifyListeners();

    try {
      final success = await _repository.adjustStock(
        product: product,
        deltaQuantity: deltaQuantity,
        direction: direction,
        reason: reason,
        warehouseId: warehouseId,
      );

      if (success) {
        await loadInventory();
      }
      return success;
    } catch (e) {
      _errorMessage = e.toString();
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<bool> countStock({
    required Product product,
    required int countedQuantity,
    String? warehouseId,
  }) async {
    _isLoading = true;
    notifyListeners();

    try {
      final success = await _repository.countStock(
        product: product,
        countedQuantity: countedQuantity,
        warehouseId: warehouseId,
      );

      if (success) {
        await loadInventory();
      }
      return success;
    } catch (e) {
      _errorMessage = e.toString();
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<Product?> createProduct({
    required String name,
    required String price,
    String? barcode,
    String? sku,
    String? category,
    int initialStock = 0,
    String? costPrice,
  }) async {
    _isLoading = true;
    notifyListeners();

    try {
      final product = await _repository.createProduct(
        name: name,
        price: price,
        barcode: barcode,
        sku: sku,
        category: category,
        initialStock: initialStock,
        costPrice: costPrice,
      );
      await loadInventory();
      return product;
    } catch (e) {
      _errorMessage = e.toString();
      return null;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<SyncResult> syncQueue() async {
    _isSyncing = true;
    notifyListeners();

    try {
      final result = await _syncEngine.syncPendingOperations();
      await loadInventory();
      return result;
    } finally {
      _isSyncing = false;
      notifyListeners();
    }
  }
}
