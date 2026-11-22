import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_ar.dart';
import 'app_localizations_en.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of AppLocalizations
/// returned by `AppLocalizations.of(context)`.
///
/// Applications need to include `AppLocalizations.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'generated/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: AppLocalizations.localizationsDelegates,
///   supportedLocales: AppLocalizations.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the AppLocalizations.supportedLocales
/// property.
abstract class AppLocalizations {
  AppLocalizations(String locale) : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static AppLocalizations? of(BuildContext context) {
    return Localizations.of<AppLocalizations>(context, AppLocalizations);
  }

  static const LocalizationsDelegate<AppLocalizations> delegate = _AppLocalizationsDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates = <LocalizationsDelegate<dynamic>>[
    delegate,
    GlobalMaterialLocalizations.delegate,
    GlobalCupertinoLocalizations.delegate,
    GlobalWidgetsLocalizations.delegate,
  ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('ar'),
    Locale('en')
  ];

  /// عنوان التطبيق
  ///
  /// In ar, this message translates to:
  /// **'فهرست'**
  String get appTitle;

  /// No description provided for @navDashboard.
  ///
  /// In ar, this message translates to:
  /// **'الرئيسية'**
  String get navDashboard;

  /// No description provided for @navCashier.
  ///
  /// In ar, this message translates to:
  /// **'الكاشير'**
  String get navCashier;

  /// No description provided for @navInventory.
  ///
  /// In ar, this message translates to:
  /// **'المخزون'**
  String get navInventory;

  /// No description provided for @navInbox.
  ///
  /// In ar, this message translates to:
  /// **'المحادثات'**
  String get navInbox;

  /// No description provided for @navSettings.
  ///
  /// In ar, this message translates to:
  /// **'الإعدادات'**
  String get navSettings;

  /// No description provided for @loginTitle.
  ///
  /// In ar, this message translates to:
  /// **'تسجيل الدخول'**
  String get loginTitle;

  /// No description provided for @loginSubtitle.
  ///
  /// In ar, this message translates to:
  /// **'أدخل بيانات حسابك للمتابعة إلى متجرك'**
  String get loginSubtitle;

  /// No description provided for @tenantSubdomain.
  ///
  /// In ar, this message translates to:
  /// **'معرّف المتجر (Subdomain)'**
  String get tenantSubdomain;

  /// No description provided for @tenantSubdomainHint.
  ///
  /// In ar, this message translates to:
  /// **'مثال: my-store'**
  String get tenantSubdomainHint;

  /// No description provided for @email.
  ///
  /// In ar, this message translates to:
  /// **'البريد الإلكتروني'**
  String get email;

  /// No description provided for @password.
  ///
  /// In ar, this message translates to:
  /// **'كلمة المرور'**
  String get password;

  /// No description provided for @loginButton.
  ///
  /// In ar, this message translates to:
  /// **'دخول'**
  String get loginButton;

  /// No description provided for @logoutButton.
  ///
  /// In ar, this message translates to:
  /// **'تسجيل الخروج'**
  String get logoutButton;

  /// No description provided for @invalidCredentials.
  ///
  /// In ar, this message translates to:
  /// **'بيانات الدخول غير صحيحة'**
  String get invalidCredentials;

  /// No description provided for @dashboardTitle.
  ///
  /// In ar, this message translates to:
  /// **'لوحة المبيعات'**
  String get dashboardTitle;

  /// No description provided for @todaySales.
  ///
  /// In ar, this message translates to:
  /// **'مبيعات اليوم'**
  String get todaySales;

  /// No description provided for @todayOrders.
  ///
  /// In ar, this message translates to:
  /// **'طلبات اليوم'**
  String get todayOrders;

  /// No description provided for @averageOrderValue.
  ///
  /// In ar, this message translates to:
  /// **'متوسط قيمة الطلب'**
  String get averageOrderValue;

  /// No description provided for @lowStockAlerts.
  ///
  /// In ar, this message translates to:
  /// **'تنبيهات انخفاض المخزون'**
  String get lowStockAlerts;

  /// No description provided for @recentOrders.
  ///
  /// In ar, this message translates to:
  /// **'أحدث الطلبات'**
  String get recentOrders;

  /// No description provided for @orderStatusCompleted.
  ///
  /// In ar, this message translates to:
  /// **'مكتمل'**
  String get orderStatusCompleted;

  /// No description provided for @orderStatusPending.
  ///
  /// In ar, this message translates to:
  /// **'قيد المعالجة'**
  String get orderStatusPending;

  /// No description provided for @orderStatusCancelled.
  ///
  /// In ar, this message translates to:
  /// **'ملغي'**
  String get orderStatusCancelled;

  /// No description provided for @cashierTitle.
  ///
  /// In ar, this message translates to:
  /// **'نقطة البيع (POS)'**
  String get cashierTitle;

  /// No description provided for @searchProductHint.
  ///
  /// In ar, this message translates to:
  /// **'بحث عن منتج بالاسم أو الباركود...'**
  String get searchProductHint;

  /// No description provided for @scanBarcode.
  ///
  /// In ar, this message translates to:
  /// **'مسح الباركود'**
  String get scanBarcode;

  /// No description provided for @cartTitle.
  ///
  /// In ar, this message translates to:
  /// **'سلة المشتريات'**
  String get cartTitle;

  /// No description provided for @emptyCart.
  ///
  /// In ar, this message translates to:
  /// **'السلة فارغة، اختر منتجات لإضافتها'**
  String get emptyCart;

  /// No description provided for @subtotal.
  ///
  /// In ar, this message translates to:
  /// **'المجموع الفرعي'**
  String get subtotal;

  /// No description provided for @tax.
  ///
  /// In ar, this message translates to:
  /// **'ضريبة القيمة المضافة'**
  String get tax;

  /// No description provided for @discount.
  ///
  /// In ar, this message translates to:
  /// **'الخصم'**
  String get discount;

  /// No description provided for @total.
  ///
  /// In ar, this message translates to:
  /// **'الإجمالي النهائي'**
  String get total;

  /// No description provided for @payCash.
  ///
  /// In ar, this message translates to:
  /// **'دفع نقدي'**
  String get payCash;

  /// No description provided for @payCard.
  ///
  /// In ar, this message translates to:
  /// **'دفع إلكتروني / بطاقة'**
  String get payCard;

  /// No description provided for @checkout.
  ///
  /// In ar, this message translates to:
  /// **'إتمام البيع'**
  String get checkout;

  /// No description provided for @holdCart.
  ///
  /// In ar, this message translates to:
  /// **'تعليق الفاتورة'**
  String get holdCart;

  /// No description provided for @cartHeldSuccess.
  ///
  /// In ar, this message translates to:
  /// **'تم تعليق الفاتورة بنجاح'**
  String get cartHeldSuccess;

  /// No description provided for @saleCompletedSuccess.
  ///
  /// In ar, this message translates to:
  /// **'تمت عملية البيع بنجاح!'**
  String get saleCompletedSuccess;

  /// No description provided for @receiptNumber.
  ///
  /// In ar, this message translates to:
  /// **'رقم الفاتورة'**
  String get receiptNumber;

  /// No description provided for @inventoryTitle.
  ///
  /// In ar, this message translates to:
  /// **'المخزون والجرد السريع'**
  String get inventoryTitle;

  /// No description provided for @searchInventoryHint.
  ///
  /// In ar, this message translates to:
  /// **'بحث بالاسم، الباركود أو SKU...'**
  String get searchInventoryHint;

  /// No description provided for @filterAll.
  ///
  /// In ar, this message translates to:
  /// **'الكل'**
  String get filterAll;

  /// No description provided for @filterLowStock.
  ///
  /// In ar, this message translates to:
  /// **'نواقص المخزون'**
  String get filterLowStock;

  /// No description provided for @filterOutOfStock.
  ///
  /// In ar, this message translates to:
  /// **'نفد المخزون'**
  String get filterOutOfStock;

  /// No description provided for @adjustStock.
  ///
  /// In ar, this message translates to:
  /// **'تعديل الرصيد'**
  String get adjustStock;

  /// No description provided for @stockCount.
  ///
  /// In ar, this message translates to:
  /// **'جرد سريع'**
  String get stockCount;

  /// No description provided for @currentStock.
  ///
  /// In ar, this message translates to:
  /// **'الرصيد الحالي'**
  String get currentStock;

  /// No description provided for @newStock.
  ///
  /// In ar, this message translates to:
  /// **'الرصيد الفعلي'**
  String get newStock;

  /// No description provided for @reason.
  ///
  /// In ar, this message translates to:
  /// **'السبب'**
  String get reason;

  /// No description provided for @reasonAdjustment.
  ///
  /// In ar, this message translates to:
  /// **'تسوية مخزنية'**
  String get reasonAdjustment;

  /// No description provided for @reasonDamage.
  ///
  /// In ar, this message translates to:
  /// **'تالف أو منتهي'**
  String get reasonDamage;

  /// No description provided for @reasonDeficit.
  ///
  /// In ar, this message translates to:
  /// **'عجز أو مفقود'**
  String get reasonDeficit;

  /// No description provided for @reasonStocktake.
  ///
  /// In ar, this message translates to:
  /// **'جرد دوري'**
  String get reasonStocktake;

  /// No description provided for @confirmAdjustment.
  ///
  /// In ar, this message translates to:
  /// **'تأكيد التسوية'**
  String get confirmAdjustment;

  /// No description provided for @adjustmentSuccess.
  ///
  /// In ar, this message translates to:
  /// **'تم تسجيل الحركة وتحديث الرصيد'**
  String get adjustmentSuccess;

  /// No description provided for @offlineQueued.
  ///
  /// In ar, this message translates to:
  /// **'تم الحفظ محلياً وسيتم المزامنة تلقائياً'**
  String get offlineQueued;

  /// No description provided for @inboxTitle.
  ///
  /// In ar, this message translates to:
  /// **'المحادثات الموحدة'**
  String get inboxTitle;

  /// No description provided for @searchConversations.
  ///
  /// In ar, this message translates to:
  /// **'بحث في المحادثات...'**
  String get searchConversations;

  /// No description provided for @channelWhatsApp.
  ///
  /// In ar, this message translates to:
  /// **'واتساب'**
  String get channelWhatsApp;

  /// No description provided for @channelInstagram.
  ///
  /// In ar, this message translates to:
  /// **'انستجرام'**
  String get channelInstagram;

  /// No description provided for @channelTelegram.
  ///
  /// In ar, this message translates to:
  /// **'تيليجرام'**
  String get channelTelegram;

  /// No description provided for @typeMessageHint.
  ///
  /// In ar, this message translates to:
  /// **'اكتب رسالتك هنا...'**
  String get typeMessageHint;

  /// No description provided for @send.
  ///
  /// In ar, this message translates to:
  /// **'إرسال'**
  String get send;

  /// No description provided for @aiAgentActive.
  ///
  /// In ar, this message translates to:
  /// **'وكيل المبيعات الذكي نشط'**
  String get aiAgentActive;

  /// No description provided for @settingsTitle.
  ///
  /// In ar, this message translates to:
  /// **'الإعدادات'**
  String get settingsTitle;

  /// No description provided for @language.
  ///
  /// In ar, this message translates to:
  /// **'اللغة'**
  String get language;

  /// No description provided for @languageArabic.
  ///
  /// In ar, this message translates to:
  /// **'العربية'**
  String get languageArabic;

  /// No description provided for @languageEnglish.
  ///
  /// In ar, this message translates to:
  /// **'English'**
  String get languageEnglish;

  /// No description provided for @darkMode.
  ///
  /// In ar, this message translates to:
  /// **'الوضع الليلي'**
  String get darkMode;

  /// No description provided for @storeInfo.
  ///
  /// In ar, this message translates to:
  /// **'معلومات المتجر'**
  String get storeInfo;

  /// No description provided for @userProfile.
  ///
  /// In ar, this message translates to:
  /// **'الملف الشخصي'**
  String get userProfile;

  /// No description provided for @currencySar.
  ///
  /// In ar, this message translates to:
  /// **'ر.س'**
  String get currencySar;

  /// No description provided for @errorGeneric.
  ///
  /// In ar, this message translates to:
  /// **'حدث خطأ غير متوقع'**
  String get errorGeneric;

  /// No description provided for @retry.
  ///
  /// In ar, this message translates to:
  /// **'إعادة المحاولة'**
  String get retry;

  /// No description provided for @cancel.
  ///
  /// In ar, this message translates to:
  /// **'إلغاء'**
  String get cancel;

  /// No description provided for @save.
  ///
  /// In ar, this message translates to:
  /// **'حفظ'**
  String get save;

  /// No description provided for @loading.
  ///
  /// In ar, this message translates to:
  /// **'جاري التحميل...'**
  String get loading;

  /// No description provided for @addProduct.
  ///
  /// In ar, this message translates to:
  /// **'إضافة منتج جديد'**
  String get addProduct;

  /// No description provided for @productName.
  ///
  /// In ar, this message translates to:
  /// **'اسم المنتج'**
  String get productName;

  /// No description provided for @price.
  ///
  /// In ar, this message translates to:
  /// **'سعر البيع'**
  String get price;

  /// No description provided for @category.
  ///
  /// In ar, this message translates to:
  /// **'التصنيف'**
  String get category;

  /// No description provided for @initialStock.
  ///
  /// In ar, this message translates to:
  /// **'الكمية الافتتاحية'**
  String get initialStock;

  /// No description provided for @productAddedSuccess.
  ///
  /// In ar, this message translates to:
  /// **'تمت إضافة المنتج بنجاح'**
  String get productAddedSuccess;

  /// No description provided for @shareInvoice.
  ///
  /// In ar, this message translates to:
  /// **'مشاركة الفاتورة'**
  String get shareInvoice;

  /// No description provided for @shareViaWhatsApp.
  ///
  /// In ar, this message translates to:
  /// **'مشاركة عبر واتساب'**
  String get shareViaWhatsApp;

  /// No description provided for @syncLog.
  ///
  /// In ar, this message translates to:
  /// **'سجل المزامنة والعمليات'**
  String get syncLog;

  /// No description provided for @syncConflicts.
  ///
  /// In ar, this message translates to:
  /// **'التعارضات'**
  String get syncConflicts;

  /// No description provided for @resolveConflict.
  ///
  /// In ar, this message translates to:
  /// **'معالجة التعارض'**
  String get resolveConflict;

  /// No description provided for @discard.
  ///
  /// In ar, this message translates to:
  /// **'حذف'**
  String get discard;
}

class _AppLocalizationsDelegate extends LocalizationsDelegate<AppLocalizations> {
  const _AppLocalizationsDelegate();

  @override
  Future<AppLocalizations> load(Locale locale) {
    return SynchronousFuture<AppLocalizations>(lookupAppLocalizations(locale));
  }

  @override
  bool isSupported(Locale locale) => <String>['ar', 'en'].contains(locale.languageCode);

  @override
  bool shouldReload(_AppLocalizationsDelegate old) => false;
}

AppLocalizations lookupAppLocalizations(Locale locale) {


  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'ar': return AppLocalizationsAr();
    case 'en': return AppLocalizationsEn();
  }

  throw FlutterError(
    'AppLocalizations.delegate failed to load unsupported locale "$locale". This is likely '
    'an issue with the localizations generation tool. Please file an issue '
    'on GitHub with a reproducible sample app and the gen-l10n configuration '
    'that was used.'
  );
}
