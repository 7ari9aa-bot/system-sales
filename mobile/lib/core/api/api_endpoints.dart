class ApiEndpoints {
  // Base default URL for local/production
  static const String defaultBaseUrl = 'https://api.fihrist.world';
  static const String localBaseUrl = 'http://10.0.2.2:8000'; // Android emulator to host

  // Auth
  static const String login = '/api/v1/auth/login';
  static const String logout = '/api/v1/auth/logout';
  static const String refresh = '/api/v1/auth/refresh';
  static const String me = '/api/v1/auth/me';

  // Analytics & Dashboard
  static const String dashboard = '/api/v1/analytics/dashboard';
  static const String revenueSummary = '/api/v1/analytics/revenue/summary';

  // POS
  static const String posSessions = '/api/v1/pos/sessions';
  static const String posStock = '/api/v1/pos/stock';
  static String posScan(String sessionId) => '/api/v1/pos/sessions/$sessionId/scan';
  static String posItems(String sessionId) => '/api/v1/pos/sessions/$sessionId/items';
  static String posQuote(String sessionId) => '/api/v1/pos/sessions/$sessionId/quote';
  static String posReceipts(String sessionId) => '/api/v1/pos/sessions/$sessionId/receipts';
  static String posHeldCarts(String sessionId) => '/api/v1/pos/sessions/$sessionId/held-carts';

  // Conversations & Unified Inbox
  static const String conversations = '/api/v1/conversations';
  static String conversationMessages(String conversationId) =>
      '/api/v1/conversations/$conversationId/messages';
  static String conversationRead(String conversationId) =>
      '/api/v1/conversations/$conversationId/read';
}
