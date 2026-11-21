// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Arabic (`ar`).
class AppLocalizationsAr extends AppLocalizations {
  AppLocalizationsAr([String locale = 'ar']) : super(locale);

  @override
  String get appTitle => 'فهرست';

  @override
  String get navDashboard => 'الرئيسية';

  @override
  String get navCashier => 'الكاشير';

  @override
  String get navInbox => 'المحادثات';

  @override
  String get navSettings => 'الإعدادات';

  @override
  String get loginTitle => 'تسجيل الدخول';

  @override
  String get loginSubtitle => 'أدخل بيانات حسابك للمتابعة إلى متجرك';

  @override
  String get tenantSubdomain => 'معرّف المتجر (Subdomain)';

  @override
  String get tenantSubdomainHint => 'مثال: my-store';

  @override
  String get email => 'البريد الإلكتروني';

  @override
  String get password => 'كلمة المرور';

  @override
  String get loginButton => 'دخول';

  @override
  String get logoutButton => 'تسجيل الخروج';

  @override
  String get invalidCredentials => 'بيانات الدخول غير صحيحة';

  @override
  String get dashboardTitle => 'لوحة المبيعات';

  @override
  String get todaySales => 'مبيعات اليوم';

  @override
  String get todayOrders => 'طلبات اليوم';

  @override
  String get averageOrderValue => 'متوسط قيمة الطلب';

  @override
  String get lowStockAlerts => 'تنبيهات انخفاض المخزون';

  @override
  String get recentOrders => 'أحدث الطلبات';

  @override
  String get orderStatusCompleted => 'مكتمل';

  @override
  String get orderStatusPending => 'قيد المعالجة';

  @override
  String get orderStatusCancelled => 'ملغي';

  @override
  String get cashierTitle => 'نقطة البيع (POS)';

  @override
  String get searchProductHint => 'بحث عن منتج بالاسم أو الباركود...';

  @override
  String get scanBarcode => 'مسح الباركود';

  @override
  String get cartTitle => 'سلة المشتريات';

  @override
  String get emptyCart => 'السلة فارغة، اختر منتجات لإضافتها';

  @override
  String get subtotal => 'المجموع الفرعي';

  @override
  String get tax => 'ضريبة القيمة المضافة';

  @override
  String get discount => 'الخصم';

  @override
  String get total => 'الإجمالي النهائي';

  @override
  String get payCash => 'دفع نقدي';

  @override
  String get payCard => 'دفع إلكتروني / بطاقة';

  @override
  String get checkout => 'إتمام البيع';

  @override
  String get holdCart => 'تعليق الفاتورة';

  @override
  String get cartHeldSuccess => 'تم تعليق الفاتورة بنجاح';

  @override
  String get saleCompletedSuccess => 'تمت عملية البيع بنجاح!';

  @override
  String get receiptNumber => 'رقم الفاتورة';

  @override
  String get inboxTitle => 'المحادثات الموحدة';

  @override
  String get searchConversations => 'بحث في المحادثات...';

  @override
  String get channelWhatsApp => 'واتساب';

  @override
  String get channelInstagram => 'انستجرام';

  @override
  String get channelTelegram => 'تيليجرام';

  @override
  String get typeMessageHint => 'اكتب رسالتك هنا...';

  @override
  String get send => 'إرسال';

  @override
  String get aiAgentActive => 'وكيل المبيعات الذكي نشط';

  @override
  String get settingsTitle => 'الإعدادات';

  @override
  String get language => 'اللغة';

  @override
  String get languageArabic => 'العربية';

  @override
  String get languageEnglish => 'English';

  @override
  String get darkMode => 'الوضع الليلي';

  @override
  String get storeInfo => 'معلومات المتجر';

  @override
  String get userProfile => 'الملف الشخصي';

  @override
  String get currencySar => 'ر.س';

  @override
  String get errorGeneric => 'حدث خطأ غير متوقع';

  @override
  String get retry => 'إعادة المحاولة';

  @override
  String get cancel => 'إلغاء';

  @override
  String get save => 'حفظ';

  @override
  String get loading => 'جاري التحميل...';
}
