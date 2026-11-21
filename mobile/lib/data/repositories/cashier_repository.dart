import '../../core/api/api_client.dart';
import '../../core/api/api_endpoints.dart';
import '../models/product.dart';

class CashierRepository {
  CashierRepository({ApiClient? apiClient})
      : _apiClient = apiClient ?? ApiClient();

  final ApiClient _apiClient;
  String? _activeSessionId;

  String? get activeSessionId => _activeSessionId;

  Future<String> getOrOpenSession() async {
    if (_activeSessionId != null) return _activeSessionId!;

    try {
      final response = await _apiClient.get(ApiEndpoints.posSessions);
      if (response is List && response.isNotEmpty) {
        _activeSessionId = response[0]['id']?.toString();
        return _activeSessionId!;
      }
    } catch (_) {}

    // Open new session
    final openResp = await _apiClient.post(
      ApiEndpoints.posSessions,
      body: {'opening_balance': '0.00'},
    );
    _activeSessionId = openResp['id']?.toString() ?? 'session_default';
    return _activeSessionId!;
  }

  Future<Product?> scanBarcode(String barcode) async {
    final sessionId = await getOrOpenSession();
    try {
      final response = await _apiClient.post(
        ApiEndpoints.posScan(sessionId),
        body: {'barcode': barcode.trim()},
      );

      if (response is Map<String, dynamic>) {
        final productJson = response['product'] ?? response;
        return Product.fromJson(productJson as Map<String, dynamic>);
      }
    } catch (_) {
      // Fallback search in stock
      final results = await searchProducts(barcode);
      if (results.isNotEmpty) {
        return results.first;
      }
    }
    return null;
  }

  Future<List<Product>> searchProducts(String query) async {
    try {
      final response = await _apiClient.get(
        ApiEndpoints.posStock,
        queryParams: {'search': query},
      );

      if (response is List) {
        return response
            .map((item) => Product.fromJson(item as Map<String, dynamic>))
            .toList();
      }
    } catch (_) {}

    // Provide default demo products if offline/unreachable
    return _mockProducts.where((p) {
      final q = query.toLowerCase();
      return p.name.toLowerCase().contains(q) ||
          (p.barcode != null && p.barcode!.contains(q));
    }).toList();
  }

  Future<Map<String, dynamic>> checkout({
    required List<CartItem> items,
    required String paymentMethod, // "cash" or "card"
    required String total,
    String? customerId,
  }) async {
    final sessionId = await getOrOpenSession();

    final payload = {
      'payment_method': paymentMethod,
      'total': total,
      'items': items
          .map((item) => {
                'product_id': item.product.id,
                'quantity': item.quantity,
                'unit_price': item.effectiveUnitPrice,
                'line_total': item.lineTotal,
              })
          .toList(),
    };

    final response = await _apiClient.post(
      ApiEndpoints.posReceipts(sessionId),
      body: payload,
    );

    return (response is Map<String, dynamic>)
        ? response
        : {'receipt_number': 'REC-${DateTime.now().millisecondsSinceEpoch}'};
  }

  static final List<Product> _mockProducts = [
    const Product(
      id: 'p1',
      name: 'قهوة عربي فاخرة 250جم',
      barcode: '6281001001',
      price: '35.00',
      stockQuantity: 42,
      category: 'مشروبات',
    ),
    const Product(
      id: 'p2',
      name: 'تمر سكري ملكي 1كجم',
      barcode: '6281001002',
      price: '65.00',
      stockQuantity: 18,
      category: 'تمور',
    ),
    const Product(
      id: 'p3',
      name: 'هيل أمريكي جامبو 100جم',
      barcode: '6281001003',
      price: '48.00',
      stockQuantity: 25,
      category: 'بهارات',
    ),
    const Product(
      id: 'p4',
      name: 'زعفران سوبر نقيل 5جم',
      barcode: '6281001004',
      price: '120.00',
      stockQuantity: 12,
      category: 'بهارات',
    ),
    const Product(
      id: 'p5',
      name: 'شاي تلقيمة فاخر 400جم',
      barcode: '6281001005',
      price: '28.00',
      stockQuantity: 60,
      category: 'مشروبات',
    ),
  ];
}
