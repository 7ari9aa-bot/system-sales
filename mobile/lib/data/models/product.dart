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
    return Product(
      id: json['id']?.toString() ?? '',
      name: json['name']?.toString() ?? '',
      barcode: json['barcode']?.toString(),
      sku: json['sku']?.toString(),
      price: json['price']?.toString() ?? json['unit_price']?.toString() ?? '0.00',
      costPrice: json['cost_price']?.toString(),
      category: json['category']?.toString(),
      stockQuantity: (json['stock_quantity'] as num?)?.toInt() ??
          (json['stock'] as num?)?.toInt() ??
          0,
      imageUrl: json['image_url']?.toString(),
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
