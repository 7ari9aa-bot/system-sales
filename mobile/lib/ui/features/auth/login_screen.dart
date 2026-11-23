import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';
import '../../../core/api/api_endpoints.dart';
import '../../../core/auth/auth_token_store.dart';
import '../../../core/constants/app_colors.dart';
import '../../../l10n/generated/app_localizations.dart';
import '../../../providers/auth_view_model.dart';
import '../../../providers/locale_view_model.dart';
import '../../widgets/fihrist_logo.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _emailController = TextEditingController(text: 'demo@salesos-demo.com');
  final _passwordController = TextEditingController(text: 'Demo-1234');
  final _tokenStore = AuthTokenStore();

  bool _obscurePassword = true;
  String _activeServerUrl = ApiEndpoints.defaultBaseUrl;
  int _logoTapCount = 0;
  DateTime? _lastLogoTap;

  @override
  void initState() {
    super.initState();
    _loadServerUrl();
  }

  Future<void> _loadServerUrl() async {
    final saved = await _tokenStore.getBaseUrl();
    if (saved != null && saved.trim().isNotEmpty) {
      if (mounted) {
        setState(() {
          _activeServerUrl = saved.trim();
        });
      }
    }
  }

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _handleLogin() async {
    if (!_formKey.currentState!.validate()) return;

    final authVm = context.read<AuthViewModel>();
    final success = await authVm.login(
      email: _emailController.text.trim(),
      password: _passwordController.text,
    );

    if (!mounted) return;

    if (!success && authVm.errorMessage != null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(authVm.errorMessage!),
          backgroundColor: AppColors.error,
          behavior: SnackBarBehavior.floating,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
          duration: const Duration(seconds: 4),
        ),
      );
    }
  }

  Future<void> _fillAndLoginDemo() async {
    _emailController.text = 'demo@salesos-demo.com';
    _passwordController.text = 'Demo-1234';
    await _handleLogin();
  }

  Future<void> _handleBiometricLogin() async {
    final authVm = context.read<AuthViewModel>();
    final success = await authVm.loginWithBiometrics();

    if (!mounted) return;

    if (!success && authVm.errorMessage != null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(authVm.errorMessage!),
          backgroundColor: AppColors.error,
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  void _onLogoTap() {
    final now = DateTime.now();
    if (_lastLogoTap == null || now.difference(_lastLogoTap!) > const Duration(seconds: 2)) {
      _logoTapCount = 1;
    } else {
      _logoTapCount++;
    }
    _lastLogoTap = now;

    if (_logoTapCount >= 5) {
      _logoTapCount = 0;
      _openServerSettings();
    }
  }

  void _openServerSettings() {
    final controller = TextEditingController(text: _activeServerUrl);
    bool testing = false;
    String? testResult;
    bool testSuccess = false;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) {
        return StatefulBuilder(
          builder: (ctx, setSheetState) {
            Future<void> runTest() async {
              final raw = controller.text.trim();
              if (raw.isEmpty) return;

              setSheetState(() {
                testing = true;
                testResult = null;
              });

              try {
                final uri = Uri.parse(raw);
                final res = await http.get(uri).timeout(const Duration(seconds: 5));
                setSheetState(() {
                  testing = false;
                  testSuccess = res.statusCode >= 200 && res.statusCode < 500;
                  testResult = testSuccess
                      ? 'تم الاتصال بالخادم بنجاح (HTTP ${res.statusCode})'
                      : 'فشل الاتصال: رمز الاستجابة ${res.statusCode}';
                });
              } catch (e) {
                setSheetState(() {
                  testing = false;
                  testSuccess = false;
                  testResult = 'تعذر الوصول إلى الخادم: $e';
                });
              }
            }

            return Padding(
              padding: EdgeInsets.only(
                left: 20,
                right: 20,
                top: 20,
                bottom: MediaQuery.of(ctx).viewInsets.bottom + 24,
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text(
                        'إعدادات الاتصال بالخادم (المطورين)',
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.close),
                        onPressed: () => Navigator.pop(ctx),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: controller,
                    decoration: const InputDecoration(
                      labelText: 'عنوان الخادم',
                      hintText: 'https://fihrist.world',
                      prefixIcon: Icon(Icons.dns_outlined),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 8,
                    children: [
                      ActionChip(
                        avatar: const Icon(Icons.cloud_done_outlined, size: 16),
                        label: const Text('الخادم الرسمي'),
                        onPressed: () {
                          controller.text = ApiEndpoints.defaultBaseUrl;
                          setSheetState(() {});
                        },
                      ),
                      ActionChip(
                        avatar: const Icon(Icons.developer_mode_outlined, size: 16),
                        label: const Text('محاكي أندرويد (10.0.2.2)'),
                        onPressed: () {
                          controller.text = ApiEndpoints.localBaseUrl;
                          setSheetState(() {});
                        },
                      ),
                    ],
                  ),
                  const SizedBox(height: 14),
                  if (testResult != null) ...[
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                      decoration: BoxDecoration(
                        color: testSuccess
                            ? AppColors.success.withValues(alpha: 0.12)
                            : AppColors.error.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(
                          color: testSuccess ? AppColors.success : AppColors.error,
                        ),
                      ),
                      child: Text(
                        testResult!,
                        style: TextStyle(
                          fontSize: 12,
                          color: testSuccess ? AppColors.success : AppColors.error,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                  ],
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: testing ? null : runTest,
                          icon: testing
                              ? const SizedBox(
                                  width: 14,
                                  height: 14,
                                  child: CircularProgressIndicator(strokeWidth: 2),
                                )
                              : const Icon(Icons.network_check, size: 18),
                          label: const Text('فحص الاتصال'),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: ElevatedButton(
                          onPressed: () async {
                            final raw = controller.text.trim();
                            if (raw.isNotEmpty) {
                              await _tokenStore.setBaseUrl(raw);
                              if (mounted) {
                                setState(() {
                                  _activeServerUrl = raw;
                                });
                              }
                            }
                            if (ctx.mounted) Navigator.pop(ctx);
                          },
                          style: ElevatedButton.styleFrom(
                            backgroundColor: AppColors.primary,
                            foregroundColor: Colors.white,
                          ),
                          child: const Text('حفظ'),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final localeVm = context.watch<LocaleViewModel>();
    final authVm = context.watch<AuthViewModel>();
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.appTitle),
        centerTitle: false,
        actions: [
          TextButton.icon(
            onPressed: () => localeVm.toggleLanguage(),
            icon: const Icon(Icons.language, size: 20),
            label: Text(localeVm.isArabic ? 'English' : 'العربية'),
          ),
          IconButton(
            onPressed: () => localeVm.toggleTheme(),
            icon: Icon(isDark ? Icons.light_mode : Icons.dark_mode),
            tooltip: l10n.darkMode,
          ),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // Official FIHRIST Brand Logo (Tappable 5x for hidden developer menu)
                    Center(
                      child: GestureDetector(
                        onTap: _onLogoTap,
                        behavior: HitTestBehavior.opaque,
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const FihristBrandMark(size: 80),
                            const SizedBox(height: 12),
                            Text(
                              localeVm.isArabic ? 'فهرس' : 'FIHRIST',
                              style: Theme.of(context).textTheme.titleLarge?.copyWith(
                                    fontWeight: FontWeight.bold,
                                    color: AppColors.primary,
                                    letterSpacing: 1.1,
                                  ),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 20),

                    // Titles
                    Text(
                      l10n.loginTitle,
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                            fontWeight: FontWeight.bold,
                          ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      l10n.loginSubtitle,
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                            color: isDark
                                ? AppColors.textSecondaryDark
                                : AppColors.textSecondaryLight,
                          ),
                    ),
                    const SizedBox(height: 32),

                    // Email Field
                    Text(
                      l10n.email,
                      style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
                    ),
                    const SizedBox(height: 8),
                    TextFormField(
                      controller: _emailController,
                      keyboardType: TextInputType.emailAddress,
                      textDirection: TextDirection.ltr,
                      decoration: const InputDecoration(
                        hintText: 'name@example.com',
                        prefixIcon: Icon(Icons.email_outlined),
                      ),
                      validator: (value) =>
                          (value == null || !value.contains('@'))
                              ? 'يرجى إدخال بريد إلكتروني صالح'
                              : null,
                    ),
                    const SizedBox(height: 20),

                    // Password Field
                    Text(
                      l10n.password,
                      style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
                    ),
                    const SizedBox(height: 8),
                    TextFormField(
                      controller: _passwordController,
                      obscureText: _obscurePassword,
                      textDirection: TextDirection.ltr,
                      decoration: InputDecoration(
                        prefixIcon: const Icon(Icons.lock_outline),
                        suffixIcon: IconButton(
                          icon: Icon(
                            _obscurePassword
                                ? Icons.visibility_outlined
                                : Icons.visibility_off_outlined,
                          ),
                          onPressed: () {
                            setState(() {
                              _obscurePassword = !_obscurePassword;
                            });
                          },
                        ),
                      ),
                      validator: (value) => (value == null || value.length < 4)
                          ? 'يرجى إدخال كلمة المرور'
                          : null,
                    ),
                    const SizedBox(height: 28),

                    // Submit Button
                    ElevatedButton(
                      onPressed: authVm.isLoading ? null : _handleLogin,
                      style: ElevatedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12),
                        ),
                      ),
                      child: authVm.isLoading
                          ? const SizedBox(
                              width: 24,
                              height: 24,
                              child: CircularProgressIndicator(
                                color: Colors.white,
                                strokeWidth: 2.5,
                              ),
                            )
                          : Text(
                              l10n.loginButton,
                              style: const TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.bold,
                                color: Colors.white,
                              ),
                            ),
                    ),
                    const SizedBox(height: 16),

                    // Quick Demo / Test Account Button
                    OutlinedButton.icon(
                      onPressed: authVm.isLoading ? null : _fillAndLoginDemo,
                      icon: const Icon(Icons.storefront_outlined, size: 20),
                      label: const Text(
                        'دخول تجريبي سريع (متجر الديمو)',
                        style: TextStyle(fontWeight: FontWeight.w600),
                      ),
                      style: OutlinedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12),
                        ),
                      ),
                    ),

                    // Biometric Login Button
                    if (authVm.isBiometricAvailable && authVm.isBiometricEnabled) ...[
                      const SizedBox(height: 12),
                      OutlinedButton.icon(
                        onPressed: authVm.isLoading ? null : _handleBiometricLogin,
                        icon: const Icon(Icons.fingerprint, size: 24, color: AppColors.primary),
                        label: const Text('تسجيل الدخول بالبصمة'),
                        style: OutlinedButton.styleFrom(
                          padding: const EdgeInsets.symmetric(vertical: 14),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
