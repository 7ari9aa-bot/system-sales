import '../../core/api/api_client.dart';
import '../../core/api/api_endpoints.dart';
import '../models/dashboard_stats.dart';
import '../models/order.dart';

class DashboardRepository {
  DashboardRepository({ApiClient? apiClient})
      : _apiClient = apiClient ?? ApiClient();

  final ApiClient _apiClient;

  Future<DashboardStats> getDashboardStats() async {
    try {
      final response = await _apiClient.get(ApiEndpoints.dashboard);
      if (response is Map<String, dynamic>) {
        return DashboardStats.fromJson(response);
      }
    } catch (_) {}

    // Fallback/demo statistics
    return DashboardStats(
      todaySales: '4850.00',
      todayOrdersCount: 28,
      averageOrderValue: '173.21',
      lowStockCount: 4,
      recentOrders: [
        SalesOrder(
          id: 'ord_101',
          orderNumber: '#10492',
          customerName: 'فهد القحطاني',
          totalAmount: '240.00',
          status: 'completed',
          createdAt: DateTime.now().subtract(const Duration(minutes: 12)),
          channel: 'pos',
        ),
        SalesOrder(
          id: 'ord_102',
          orderNumber: '#10491',
          customerName: 'نورة السبيعي',
          totalAmount: '135.00',
          status: 'completed',
          createdAt: DateTime.now().subtract(const Duration(minutes: 35)),
          channel: 'whatsapp',
        ),
        SalesOrder(
          id: 'ord_103',
          orderNumber: '#10490',
          customerName: 'سلطان المطيري',
          totalAmount: '510.00',
          status: 'pending',
          createdAt: DateTime.now().subtract(const Duration(hours: 1)),
          channel: 'instagram',
        ),
      ],
    );
  }
}
