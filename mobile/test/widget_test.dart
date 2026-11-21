import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:fihrist_mobile/providers/auth_view_model.dart';
import 'package:fihrist_mobile/providers/cashier_view_model.dart';
import 'package:fihrist_mobile/providers/chat_view_model.dart';
import 'package:fihrist_mobile/providers/dashboard_view_model.dart';
import 'package:fihrist_mobile/providers/locale_view_model.dart';
import 'package:fihrist_mobile/ui/app.dart';

void main() {
  testWidgets('Renders Fihrist App with Arabic-first LoginScreen', (WidgetTester tester) async {
    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider(create: (_) => LocaleViewModel()),
          ChangeNotifierProvider(create: (_) => AuthViewModel()),
          ChangeNotifierProvider(create: (_) => CashierViewModel()),
          ChangeNotifierProvider(create: (_) => ChatViewModel()),
          ChangeNotifierProvider(create: (_) => DashboardViewModel()),
        ],
        child: const FihristApp(),
      ),
    );

    // Initial pump
    await tester.pumpAndSettle();

    // Verify Login Screen widgets exist
    expect(find.byType(TextFormField), findsNWidgets(3)); // Subdomain, Email, Password
    expect(find.byType(ElevatedButton), findsOneWidget); // Submit button
  });
}
