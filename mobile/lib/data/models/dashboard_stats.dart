import 'order.dart';

class DashboardStats {
  final String todaySales; // Money string e.g. "12450.00"
  final int todayOrdersCount;
  final String averageOrderValue; // Money string e.g. "185.00"
  final int lowStockCount;
  final List<SalesOrder> recentOrders;

  const DashboardStats({
    required this.todaySales,
    required this.todayOrdersCount,
    required this.averageOrderValue,
    required this.lowStockCount,
    this.recentOrders = const [],
  });

  factory DashboardStats.fromJson(Map<String, dynamic> json) {
    return DashboardStats(
      todaySales: json['today_sales']?.toString() ??
          json['total_revenue']?.toString() ??
          '0.00',
      todayOrdersCount: (json['today_orders_count'] as num?)?.toInt() ??
          (json['orders_count'] as num?)?.toInt() ??
          0,
      averageOrderValue: json['average_order_value']?.toString() ??
          json['aov']?.toString() ??
          '0.00',
      lowStockCount: (json['low_stock_count'] as num?)?.toInt() ??
          (json['stock_alerts'] as num?)?.toInt() ??
          0,
      recentOrders: (json['recent_orders'] as List<dynamic>?)
              ?.map((e) => SalesOrder.fromJson(e as Map<String, dynamic>))
              .toList() ??
          const [],
    );
  }
}
