import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:provider/provider.dart';
import '../core/theme/app_theme.dart';
import '../l10n/generated/app_localizations.dart';
import '../providers/auth_view_model.dart';
import '../providers/locale_view_model.dart';
import 'features/auth/login_screen.dart';
import 'main_navigation.dart';

class FihristApp extends StatelessWidget {
  const FihristApp({super.key});

  @override
  Widget build(BuildContext context) {
    final localeVm = context.watch<LocaleViewModel>();
    final authVm = context.watch<AuthViewModel>();

    return MaterialApp(
      title: 'فهرست | Fihrist',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.lightTheme,
      darkTheme: AppTheme.darkTheme,
      themeMode: localeVm.themeMode,
      locale: localeVm.locale,
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: AppLocalizations.supportedLocales,
      home: _buildHome(authVm),
    );
  }

  Widget _buildHome(AuthViewModel authVm) {
    if (!authVm.isInitialized && authVm.isLoading) {
      return const Scaffold(
        body: Center(
          child: CircularProgressIndicator(),
        ),
      );
    }

    if (authVm.isAuthenticated) {
      return const MainNavigation();
    }

    return const LoginScreen();
  }
}
