class Supplier {
  final String id;
  final String name;
  final String phone;
  final String contactPerson;
  final String balanceSar;

  const Supplier({
    required this.id,
    required this.name,
    required this.phone,
    required this.contactPerson,
    required this.balanceSar,
  });

  factory Supplier.fromJson(Map<String, dynamic> json) {
    return Supplier(
      id: json['id']?.toString() ?? '',
      name: json['name']?.toString() ?? '',
      phone: json['phone']?.toString() ?? '',
      contactPerson: json['contact_person']?.toString() ?? '',
      balanceSar: json['balance_sar']?.toString() ?? '0.00',
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'phone': phone,
        'contact_person': contactPerson,
        'balance_sar': balanceSar,
      };
}

class PurchaseOrderItem {
  final String productId;
  final String productName;
  final int quantity;
  final String unitCost;
  final int receivedQuantity;

  const PurchaseOrderItem({
    required this.productId,
    required this.productName,
    required this.quantity,
    required this.unitCost,
    this.receivedQuantity = 0,
  });

  PurchaseOrderItem copyWith({
    int? receivedQuantity,
  }) {
    return PurchaseOrderItem(
      productId: productId,
      productName: productName,
      quantity: quantity,
      unitCost: unitCost,
      receivedQuantity: receivedQuantity ?? this.receivedQuantity,
    );
  }

  factory PurchaseOrderItem.fromJson(Map<String, dynamic> json) {
    return PurchaseOrderItem(
      productId: json['product_id']?.toString() ?? '',
      productName: json['product_name']?.toString() ?? '',
      quantity: (json['quantity'] as num?)?.toInt() ?? 0,
      unitCost: json['unit_cost']?.toString() ?? '0.00',
      receivedQuantity: (json['received_quantity'] as num?)?.toInt() ?? 0,
    );
  }

  Map<String, dynamic> toJson() => {
        'product_id': productId,
        'product_name': productName,
        'quantity': quantity,
        'unit_cost': unitCost,
        'received_quantity': receivedQuantity,
      };
}

enum PurchaseOrderStatus {
  pending,
  received,
  paid,
}

class PurchaseOrder {
  final String id;
  final String poNumber;
  final String supplierId;
  final String supplierName;
  final String orderDate;
  final String totalSar;
  final PurchaseOrderStatus status;
  final List<PurchaseOrderItem> items;
  final String? notes;

  const PurchaseOrder({
    required this.id,
    required this.poNumber,
    required this.supplierId,
    required this.supplierName,
    required this.orderDate,
    required this.totalSar,
    this.status = PurchaseOrderStatus.pending,
    required this.items,
    this.notes,
  });

  PurchaseOrder copyWith({
    PurchaseOrderStatus? status,
    List<PurchaseOrderItem>? items,
    String? notes,
  }) {
    return PurchaseOrder(
      id: id,
      poNumber: poNumber,
      supplierId: supplierId,
      supplierName: supplierName,
      orderDate: orderDate,
      totalSar: totalSar,
      status: status ?? this.status,
      items: items ?? this.items,
      notes: notes ?? this.notes,
    );
  }

  factory PurchaseOrder.fromJson(Map<String, dynamic> json) {
    final statusStr = json['status']?.toString() ?? 'pending';
    final status = statusStr == 'received'
        ? PurchaseOrderStatus.received
        : statusStr == 'paid'
            ? PurchaseOrderStatus.paid
            : PurchaseOrderStatus.pending;

    final rawItems = json['items'] as List<dynamic>? ?? [];
    final items = rawItems
        .map((item) => PurchaseOrderItem.fromJson(item as Map<String, dynamic>))
        .toList();

    return PurchaseOrder(
      id: json['id']?.toString() ?? '',
      poNumber: json['po_number']?.toString() ?? '',
      supplierId: json['supplier_id']?.toString() ?? '',
      supplierName: json['supplier_name']?.toString() ?? '',
      orderDate: json['order_date']?.toString() ?? '',
      totalSar: json['total_sar']?.toString() ?? '0.00',
      status: status,
      items: items,
      notes: json['notes']?.toString(),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'po_number': poNumber,
        'supplier_id': supplierId,
        'supplier_name': supplierName,
        'order_date': orderDate,
        'total_sar': totalSar,
        'status': status.name,
        'items': items.map((i) => i.toJson()).toList(),
        'notes': notes,
      };
}
