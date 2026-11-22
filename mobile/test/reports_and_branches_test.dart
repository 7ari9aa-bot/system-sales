import 'package:fihrist_mobile/data/models/branch.dart';
import 'package:fihrist_mobile/l10n/generated/app_localizations.dart';
import 'package:fihrist_mobile/providers/auth_view_model.dart';
import 'package:fihrist_mobile/providers/dashboard_view_model.dart';
import 'package:fihrist_mobile/providers/locale_view_model.dart';
import 'package:fihrist_mobile/ui/features/reports/reports_screen.dart';
import 'package:fihrist_mobile/ui/features/settings/widgets/branch_switcher_dialog.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

void main() {
  group('Branch Model & AuthViewModel Branch Management', () {
    test('Branch model serialization works accurately', () {
      const branch = Branch(
        id: 'br_test',
        name: 'فرع مكة المكرمة',
        code: 'MAK-01',
        location: 'حي العزيزية، مكة',
        isMain: false,
      );

      final json = branch.toJson();
      expect(json['id'], equals('br_test'));
      expect(json['name'], equals('فرع مكة المكرمة'));
      expect(json['code'], equals('MAK-01'));
      expect(json['location'], equals('حي العزيزية، مكة'));
      expect(json['is_main'], isFalse);

      final fromJson = Branch.fromJson(json);
      expect(fromJson.id, equals('br_test'));
      expect(fromJson.name, equals('فرع مكة المكرمة'));
      expect(fromJson.code, equals('MAK-01'));
      expect(fromJson.isMain, isFalse);
    });

    test('AuthViewModel initializes with main branch and supports switching', () {
      final authVm = AuthViewModel();
      expect(authVm.availableBranches.length, greaterThanOrEqualTo(3));
      expect(authVm.activeBranch.isMain, isTrue);
      expect(authVm.activeBranch.id, equals('br_main'));

      final secondBranch = authVm.availableBranches[1];
      authVm.switchBranch(secondBranch);
      expect(authVm.activeBranch.id, equals(secondBranch.id));
      expect(authVm.activeBranch.name, equals(secondBranch.name));
    });
  });

  group('ReportsScreen & BranchSwitcher Widgets', () {
    Widget buildTestWidget({required Widget child, AuthViewModel? authVm}) {
      final effectiveAuthVm = authVm ?? AuthViewModel();
      return MultiProvider(
        providers: [
          ChangeNotifierProvider<AuthViewModel>.value(value: effectiveAuthVm),
          ChangeNotifierProvider<DashboardViewModel>(
            create: (_) => DashboardViewModel(),
          ),
          ChangeNotifierProvider<LocaleViewModel>(
            create: (_) => LocaleViewModel(),
          ),
        ],
        child: MaterialApp(
          locale: const Locale('ar'),
          localizationsDelegates: const [
            AppLocalizations.delegate,
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
            GlobalCupertinoLocalizations.delegate,
          ],
          supportedLocales: const [
            Locale('ar'),
            Locale('en'),
          ],
          home: child,
        ),
      );
    }

    testWidgets('ReportsScreen renders tabs, KPIs and valuation', (tester) async {
      await tester.pumpWidget(
        buildTestWidget(child: const ReportsScreen()),
      );
      await tester.pumpAndSettle();

      expect(find.text('التقارير والتحليلات'), findsOneWidget);
      expect(find.text('المبيعات والمالية'), findsOneWidget);
      expect(find.text('المخزون والركود'), findsOneWidget);
      expect(find.text('مطابقة الورديات'), findsOneWidget);
      expect(find.text('توصيات الذكاء'), findsOneWidget);

      // Verify sales tab content
      expect(find.text('إجمالي المبيعات'), findsOneWidget);
      expect(find.text('توزيع طرق الدفع'), findsOneWidget);

      // Tap on Inventory tab
      await tester.tap(find.text('المخزون والركود'));
      await tester.pumpAndSettle();

      expect(find.text('إجمالي القيمة التقديرية لمخزون الفرع'), findsOneWidget);
      expect(find.text('تنبيهات المخزون الراكد (Dead Stock)'), findsOneWidget);

      // Tap on Shifts tab
      await tester.tap(find.text('مطابقة الورديات'));
      await tester.pumpAndSettle();

      expect(find.textContaining('سجل إغلاق ورديات الكاشير'), findsOneWidget);

      // Tap on AI Insights tab
      await tester.tap(find.text('توصيات الذكاء'));
      await tester.pumpAndSettle();

      expect(find.textContaining('وكيل تحليلات فهرست'), findsOneWidget);
    });

    testWidgets('BranchSwitcherDialog allows switching branches', (tester) async {
      final authVm = AuthViewModel();

      await tester.pumpWidget(
        buildTestWidget(
          authVm: authVm,
          child: Scaffold(
            body: Builder(
              builder: (ctx) => ElevatedButton(
                onPressed: () {
                  showDialog(
                    context: ctx,
                    builder: (_) => const BranchSwitcherDialog(),
                  );
                },
                child: const Text('Open Switcher'),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.text('Open Switcher'));
      await tester.pumpAndSettle();

      expect(find.text('تبديل فرع التشغيل'), findsOneWidget);
      expect(find.text('فرع جدة - الشاطئ'), findsOneWidget);

      // Tap second branch
      await tester.tap(find.text('فرع جدة - الشاطئ'));
      await tester.pumpAndSettle();

      expect(authVm.activeBranch.id, equals('br_jeddah'));
      expect(authVm.activeBranch.name, equals('فرع جدة - الشاطئ'));
    });
  });
}
