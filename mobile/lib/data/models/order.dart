class SalesOrder {
  final String id;
  final String orderNumber;
  final String? customerName;
  final String? customerPhone;
  final String status;
  final String totalAmount; // Money string e.g. "150.00"
  final int itemsCount;
  final DateTime createdAt;
  final String channel;

  const SalesOrder({
    required this.id,
    required this.orderNumber,
    this.customerName,
    this.customerPhone,
    required this.status,
    required this.totalAmount,
    this.itemsCount = 1,
    required this.createdAt,
    this.channel = 'pos',
  });

  factory SalesOrder.fromJson(Map<String, dynamic> json) {
    return SalesOrder(
      id: json['id']?.toString() ?? '',
      orderNumber: json['order_number']?.toString() ??
          json['receipt_number']?.toString() ??
          json['id']?.toString() ??
          '',
      customerName: json['customer_name']?.toString() ??
          json['customer']?['name']?.toString(),
      customerPhone: json['customer_phone']?.toString() ??
          json['customer']?['phone']?.toString(),
      status: json['status']?.toString() ?? 'completed',
      totalAmount: json['total_amount']?.toString() ??
          json['total']?.toString() ??
          '0.00',
      itemsCount: (json['items_count'] as num?)?.toInt() ??
          (json['items'] as List<dynamic>?)?.length ??
          1,
      createdAt: json['created_at'] != null
          ? DateTime.tryParse(json['created_at'].toString()) ?? DateTime.now()
          : DateTime.now(),
      channel: json['channel']?.toString() ?? 'pos',
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'order_number': orderNumber,
        'customer_name': customerName,
        'customer_phone': customerPhone,
        'status': status,
        'total_amount': totalAmount,
        'items_count': itemsCount,
        'created_at': createdAt.toIso8601String(),
        'channel': channel,
      };
}
