// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get appTitle => 'Fihrist';

  @override
  String get navDashboard => 'Dashboard';

  @override
  String get navCashier => 'POS';

  @override
  String get navInventory => 'Inventory';

  @override
  String get navInbox => 'Inbox';

  @override
  String get navSettings => 'Settings';

  @override
  String get loginTitle => 'Sign In';

  @override
  String get loginSubtitle => 'Enter your credentials to access your store';

  @override
  String get tenantSubdomain => 'Store Subdomain';

  @override
  String get tenantSubdomainHint => 'e.g. my-store';

  @override
  String get email => 'Email Address';

  @override
  String get password => 'Password';

  @override
  String get loginButton => 'Sign In';

  @override
  String get logoutButton => 'Sign Out';

  @override
  String get invalidCredentials => 'Invalid email or password';

  @override
  String get dashboardTitle => 'Sales Dashboard';

  @override
  String get todaySales => 'Today\'s Sales';

  @override
  String get todayOrders => 'Today\'s Orders';

  @override
  String get averageOrderValue => 'Avg. Order Value';

  @override
  String get lowStockAlerts => 'Low Stock Alerts';

  @override
  String get recentOrders => 'Recent Orders';

  @override
  String get orderStatusCompleted => 'Completed';

  @override
  String get orderStatusPending => 'Pending';

  @override
  String get orderStatusCancelled => 'Cancelled';

  @override
  String get cashierTitle => 'Point of Sale (POS)';

  @override
  String get searchProductHint => 'Search product by name or barcode...';

  @override
  String get scanBarcode => 'Scan Barcode';

  @override
  String get cartTitle => 'Shopping Cart';

  @override
  String get emptyCart => 'Cart is empty, tap products to add';

  @override
  String get subtotal => 'Subtotal';

  @override
  String get tax => 'VAT (15%)';

  @override
  String get discount => 'Discount';

  @override
  String get total => 'Total Amount';

  @override
  String get payCash => 'Cash Payment';

  @override
  String get payCard => 'Card Payment';

  @override
  String get checkout => 'Complete Checkout';

  @override
  String get holdCart => 'Hold Order';

  @override
  String get cartHeldSuccess => 'Order held successfully';

  @override
  String get saleCompletedSuccess => 'Sale completed successfully!';

  @override
  String get receiptNumber => 'Receipt No.';

  @override
  String get inventoryTitle => 'Inventory & Stocktaking';

  @override
  String get searchInventoryHint => 'Search by name, barcode or SKU...';

  @override
  String get filterAll => 'All';

  @override
  String get filterLowStock => 'Low Stock';

  @override
  String get filterOutOfStock => 'Out of Stock';

  @override
  String get adjustStock => 'Adjust Stock';

  @override
  String get stockCount => 'Quick Count';

  @override
  String get currentStock => 'Current Stock';

  @override
  String get newStock => 'Counted Stock';

  @override
  String get reason => 'Reason';

  @override
  String get reasonAdjustment => 'Stock Adjustment';

  @override
  String get reasonDamage => 'Damaged / Expired';

  @override
  String get reasonDeficit => 'Deficit / Missing';

  @override
  String get reasonStocktake => 'Stocktake Count';

  @override
  String get confirmAdjustment => 'Confirm Adjustment';

  @override
  String get adjustmentSuccess => 'Movement recorded and stock updated';

  @override
  String get offlineQueued => 'Saved locally and will sync when online';

  @override
  String get inboxTitle => 'Unified Inbox';

  @override
  String get searchConversations => 'Search conversations...';

  @override
  String get channelWhatsApp => 'WhatsApp';

  @override
  String get channelInstagram => 'Instagram';

  @override
  String get channelTelegram => 'Telegram';

  @override
  String get typeMessageHint => 'Type a message...';

  @override
  String get send => 'Send';

  @override
  String get aiAgentActive => 'AI Sales Agent Active';

  @override
  String get settingsTitle => 'Settings';

  @override
  String get language => 'Language';

  @override
  String get languageArabic => 'العربية';

  @override
  String get languageEnglish => 'English';

  @override
  String get darkMode => 'Dark Mode';

  @override
  String get storeInfo => 'Store Info';

  @override
  String get userProfile => 'User Profile';

  @override
  String get currencySar => 'SAR';

  @override
  String get errorGeneric => 'An unexpected error occurred';

  @override
  String get retry => 'Retry';

  @override
  String get cancel => 'Cancel';

  @override
  String get save => 'Save';

  @override
  String get loading => 'Loading...';
}
