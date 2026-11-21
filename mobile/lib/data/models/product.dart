import '../../core/utils/money_formatter.dart';

class Product {
  final String id;
  final String name;
  final String? barcode;
  final String? sku;
  final String price; // Exact decimal string e.g. "45.00"
  final String? costPrice;
  final String? category;
  final int stockQuantity;
  final String? imageUrl;

  const Product({
    required this.id,
    required this.name,
    this.barcode,
    this.sku,
    required this.price,
    this.costPrice,
    this.category,
    this.stockQuantity = 0,
    this.imageUrl,
  });

  factory Product.fromJson(Map<String, dynamic> json) {
    final id = json['variant_id']?.toString() ?? json['id']?.toString() ?? '';
    final name = json['product_title']?.toString() ?? json['name']?.toString() ?? '';
    final price = json['price']?.toString() ?? json['unit_price']?.toString() ?? '0.00';
    final onHand = (json['on_hand'] as num?)?.toInt() ??
        (json['stock_quantity'] as num?)?.toInt() ??
        (json['stock'] as num?)?.toInt() ??
        0;

    return Product(
      id: id,
      name: name,
      barcode: json['barcode']?.toString(),
      sku: json['sku']?.toString(),
      price: price,
      costPrice: json['avg_cost']?.toString() ?? json['cost_price']?.toString(),
      category: json['category']?.toString(),
      stockQuantity: onHand,
      imageUrl: json['image_url']?.toString(),
    );
  }

  Product copyWith({
    String? id,
    String? name,
    String? barcode,
    String? sku,
    String? price,
    String? costPrice,
    String? category,
    int? stockQuantity,
    String? imageUrl,
  }) {
    return Product(
      id: id ?? this.id,
      name: name ?? this.name,
      barcode: barcode ?? this.barcode,
      sku: sku ?? this.sku,
      price: price ?? this.price,
      costPrice: costPrice ?? this.costPrice,
      category: category ?? this.category,
      stockQuantity: stockQuantity ?? this.stockQuantity,
      imageUrl: imageUrl ?? this.imageUrl,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'barcode': barcode,
        'sku': sku,
        'price': price,
        'cost_price': costPrice,
        'category': category,
        'stock_quantity': stockQuantity,
        'image_url': imageUrl,
      };
}

class CartItem {
  final Product product;
  int quantity;
  String? customPrice; // Override if allowed
  String? discountAmount;

  CartItem({
    required this.product,
    this.quantity = 1,
    this.customPrice,
    this.discountAmount,
  });

  String get effectiveUnitPrice => customPrice ?? product.price;

  String get lineTotal {
    return MoneyFormatter.multiply(effectiveUnitPrice, quantity);
  }
}
