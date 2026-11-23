class ApiEndpoints {
  // إدخال منتج كامل في طلب واحد: منتج + تركيبات + باركود + رصيد (نفس مسار الويب).
  static const String productsIntake = '/api/v1/products/intake';
  static const String warehouses = '/api/v1/warehouses';
  static const String warehousesEnsureDefault = '/api/v1/warehouses/ensure-default';

  // Base default URL for local/production
  // النطاق الفرعي api.fihrist.world مابقاش له سجل DNS؛ الموقع والـAPI على نفس الأصل.
  static const String defaultBaseUrl = 'https://fihrist.world';
  static const String localBaseUrl = 'http://10.0.2.2:8000'; // Android emulator to host

  // Auth
  static const String login = '/api/v1/auth/login';
  static const String logout = '/api/v1/auth/logout';
  static const String refresh = '/api/v1/auth/refresh';
  static const String me = '/api/v1/auth/me';

  // Analytics & Dashboard
  static const String dashboard = '/api/v1/analytics/dashboard';
  static const String revenueSummary = '/api/v1/analytics/revenue/summary';

  // POS Registers & Sessions
  static const String posRegisters = '/api/v1/pos/registers';
  static String posRegisterSales(String registerId) =>
      '/api/v1/pos/registers/$registerId/sales';
  static String posRegisterOpen(String registerId) =>
      '/api/v1/pos/registers/$registerId/open-day';
  static String posRegisterWorkingSession(String registerId) =>
      '/api/v1/pos/registers/$registerId/working-session';

  static const String posSessions = '/api/v1/pos/sessions';
  static const String posStock = '/api/v1/pos/stock';
  static String posScan(String sessionId) => '/api/v1/pos/sessions/$sessionId/scan';
  static String posItems(String sessionId) => '/api/v1/pos/sessions/$sessionId/items';
  static String posQuote(String sessionId) => '/api/v1/pos/sessions/$sessionId/quote';
  static String posReceipts(String sessionId) => '/api/v1/pos/sessions/$sessionId/receipts';
  static String posHeldCarts(String sessionId) => '/api/v1/pos/sessions/$sessionId/held-carts';

  // Catalog Products
  static const String products = '/api/v1/products';

  // Purchasing & Suppliers
  static const String suppliers = '/api/v1/purchasing/suppliers';
  static const String purchaseOrders = '/api/v1/purchasing/purchase-orders';
  static String purchaseOrderReceive(String orderId) =>
      '/api/v1/purchasing/purchase-orders/$orderId/receive';

  // Conversations & Unified Inbox
  static const String inbox = '/api/v1/inbox';
  static const String conversations = '/api/v1/conversations';
  static String conversationMessages(String conversationId) =>
      '/api/v1/conversations/$conversationId/messages';
  static String conversationRead(String conversationId) =>
      '/api/v1/conversations/$conversationId/read';
}
