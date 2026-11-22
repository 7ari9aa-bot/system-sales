import 'dart:async';
import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/material.dart';
import '../core/offline/offline_queue_service.dart';
import '../core/utils/money_formatter.dart';
import '../data/models/product.dart';
import '../data/repositories/cashier_repository.dart';

class CashierViewModel extends ChangeNotifier {
  CashierViewModel({
    CashierRepository? cashierRepository,
    OfflineQueueService? offlineQueue,
  })  : _cashierRepository = cashierRepository ?? CashierRepository(),
        _offlineQueue = offlineQueue ?? OfflineQueueService() {
    searchProducts('');
    refreshOfflineCount();
    _initConnectivityListener();
  }

  final CashierRepository _cashierRepository;
  final OfflineQueueService _offlineQueue;
  StreamSubscription<List<ConnectivityResult>>? _connectivitySubscription;

  void _initConnectivityListener() {
    _connectivitySubscription = Connectivity().onConnectivityChanged.listen((results) {
      final isConnected = results.any((r) => r != ConnectivityResult.none);
      if (isConnected && _pendingOfflineCount > 0) {
        syncOfflineSales();
      }
    });
  }

  @override
  void dispose() {
    _connectivitySubscription?.cancel();
    super.dispose();
  }

  List<Product> _products = [];
  final List<CartItem> _cartItems = [];
  final List<List<CartItem>> _heldCarts = [];
  List<CartItem> _lastCompletedItems = [];
  bool _isLoading = false;
  String? _errorMessage;
  String? _lastReceiptNumber;
  bool _isLastSaleOffline = false;
  int _pendingOfflineCount = 0;

  List<Product> get products => _products;
  List<CartItem> get cartItems => List.unmodifiable(_cartItems);
  List<List<CartItem>> get heldCarts => List.unmodifiable(_heldCarts);
  List<CartItem> get lastCompletedItems => List.unmodifiable(_lastCompletedItems);
  bool get isLoading => _isLoading;
  String? get errorMessage => _errorMessage;
  String? get lastReceiptNumber => _lastReceiptNumber;
  bool get isLastSaleOffline => _isLastSaleOffline;
  int get pendingOfflineCount => _pendingOfflineCount;

  int get cartCount => _cartItems.fold(0, (sum, item) => sum + item.quantity);

  /// Total amount (VAT inclusive) using exact cents arithmetic
  String get total {
    BigInt totalCents = BigInt.zero;
    for (final item in _cartItems) {
      final unitCents = MoneyFormatter.toCents(item.effectiveUnitPrice);
      totalCents += unitCents * BigInt.from(item.quantity);
    }
    return MoneyFormatter.fromCents(totalCents);
  }

  /// 15% VAT inclusive: (totalCents * 15) ~/ 115
  String get tax {
    final totalCents = MoneyFormatter.toCents(total);
    final taxCents = (totalCents * BigInt.from(15)) ~/ BigInt.from(115);
    return MoneyFormatter.fromCents(taxCents);
  }

  /// Subtotal (before VAT): Total - VAT
  String get subtotal {
    final totalCents = MoneyFormatter.toCents(total);
    final taxCents = MoneyFormatter.toCents(tax);
    return MoneyFormatter.fromCents(totalCents - taxCents);
  }

  Future<void> searchProducts(String query) async {
    _isLoading = true;
    _errorMessage = null;
    notifyListeners();

    try {
      _products = await _cashierRepository.searchProducts(query);
    } catch (e) {
      _errorMessage = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  void addToCart(Product product) {
    final index = _cartItems.indexWhere((item) => item.product.id == product.id);
    if (index >= 0) {
      _cartItems[index].quantity += 1;
    } else {
      _cartItems.add(CartItem(product: product, quantity: 1));
    }
    notifyListeners();
  }

  void updateQuantity(Product product, int delta) {
    final index = _cartItems.indexWhere((item) => item.product.id == product.id);
    if (index >= 0) {
      final newQty = _cartItems[index].quantity + delta;
      if (newQty <= 0) {
        _cartItems.removeAt(index);
      } else {
        _cartItems[index].quantity = newQty;
      }
      notifyListeners();
    }
  }

  void removeFromCart(Product product) {
    _cartItems.removeWhere((item) => item.product.id == product.id);
    notifyListeners();
  }

  void clearCart() {
    _cartItems.clear();
    notifyListeners();
  }

  Future<bool> scanBarcode(String barcode) async {
    _isLoading = true;
    notifyListeners();

    try {
      final product = await _cashierRepository.scanBarcode(barcode);
      if (product != null) {
        addToCart(product);
        _isLoading = false;
        notifyListeners();
        return true;
      }
    } catch (_) {}

    _isLoading = false;
    notifyListeners();
    return false;
  }

  void holdCurrentCart() {
    if (_cartItems.isEmpty) return;
    _heldCarts.add(List.from(_cartItems));
    _cartItems.clear();
    notifyListeners();
  }

  void resumeHeldCart(int index) {
    if (index >= 0 && index < _heldCarts.length) {
      _cartItems.clear();
      _cartItems.addAll(_heldCarts.removeAt(index));
      notifyListeners();
    }
  }

  Future<void> refreshOfflineCount() async {
    final queue = await _offlineQueue.getPendingQueue();
    _pendingOfflineCount = queue.length;
    notifyListeners();
  }

  Future<int> syncOfflineSales() async {
    _isLoading = true;
    notifyListeners();
    try {
      final count = await _offlineQueue.syncPendingQueue(_cashierRepository);
      await refreshOfflineCount();
      return count;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<bool> checkout({required String paymentMethod}) async {
    if (_cartItems.isEmpty) return false;

    _isLoading = true;
    _errorMessage = null;
    _isLastSaleOffline = false;
    _lastCompletedItems = List.from(_cartItems);
    notifyListeners();

    try {
      final result = await _cashierRepository.checkout(
        items: _cartItems,
        paymentMethod: paymentMethod,
        total: total,
      );

      _lastReceiptNumber = result['receipt_number']?.toString() ??
          result['order_number']?.toString() ??
          'REC-${DateTime.now().millisecondsSinceEpoch}';

      _cartItems.clear();
      return true;
    } catch (_) {
      // Offline fallback: enqueue locally
      await _offlineQueue.enqueueSale(
        items: _lastCompletedItems,
        paymentMethod: paymentMethod,
        total: total,
      );
      _lastReceiptNumber = 'OFFLINE-${DateTime.now().millisecondsSinceEpoch}';
      _isLastSaleOffline = true;
      _cartItems.clear();
      await refreshOfflineCount();
      return true;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }
}
