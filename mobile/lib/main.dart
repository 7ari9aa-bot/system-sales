import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'core/notifications/notification_service.dart';
import 'core/printer/thermal_printer_manager.dart';
import 'providers/auth_view_model.dart';
import 'providers/cashier_view_model.dart';
import 'providers/chat_view_model.dart';
import 'providers/dashboard_view_model.dart';
import 'providers/inventory_view_model.dart';
import 'providers/locale_view_model.dart';
import 'providers/purchasing_view_model.dart';
import 'ui/app.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final authVm = AuthViewModel();
  // Check persisted auth session
  await authVm.checkAuthStatus();

  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => LocaleViewModel()),
        ChangeNotifierProvider.value(value: authVm),
        ChangeNotifierProvider(create: (_) => CashierViewModel()),
        ChangeNotifierProvider(create: (_) => InventoryViewModel()),
        ChangeNotifierProvider(create: (_) => ChatViewModel()),
        ChangeNotifierProvider(create: (_) => DashboardViewModel()),
        ChangeNotifierProvider(create: (_) => ThermalPrinterManager()),
        ChangeNotifierProvider(create: (_) => NotificationService()),
        ChangeNotifierProvider(create: (_) => PurchasingViewModel()),
      ],
      child: const FihristApp(),
    ),
  );
}
