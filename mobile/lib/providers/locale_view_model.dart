import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

class LocaleViewModel extends ChangeNotifier {
  static const String _keyLocale = 'app_locale';
  static const String _keyThemeMode = 'app_theme_mode';

  Locale _locale = const Locale('ar'); // Arabic first (RTL)
  ThemeMode _themeMode = ThemeMode.system;

  Locale get locale => _locale;
  ThemeMode get themeMode => _themeMode;
  bool get isArabic => _locale.languageCode == 'ar';
  bool get isDarkMode => _themeMode == ThemeMode.dark;

  LocaleViewModel() {
    _loadPreferences();
  }

  Future<void> _loadPreferences() async {
    final prefs = await SharedPreferences.getInstance();
    final langCode = prefs.getString(_keyLocale);
    if (langCode != null) {
      _locale = Locale(langCode);
    }
    final themeName = prefs.getString(_keyThemeMode);
    if (themeName == 'dark') {
      _themeMode = ThemeMode.dark;
    } else if (themeName == 'light') {
      _themeMode = ThemeMode.light;
    }
    notifyListeners();
  }

  Future<void> setLocale(Locale newLocale) async {
    if (_locale == newLocale) return;
    _locale = newLocale;
    notifyListeners();

    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyLocale, newLocale.languageCode);
  }

  Future<void> toggleLanguage() async {
    if (_locale.languageCode == 'ar') {
      await setLocale(const Locale('en'));
    } else {
      await setLocale(const Locale('ar'));
    }
  }

  Future<void> setThemeMode(ThemeMode mode) async {
    _themeMode = mode;
    notifyListeners();

    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyThemeMode, mode.name);
  }

  Future<void> toggleTheme() async {
    final newMode = _themeMode == ThemeMode.dark ? ThemeMode.light : ThemeMode.dark;
    await setThemeMode(newMode);
  }
}
