import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../core/constants/app_colors.dart';
import '../../../core/notifications/notification_service.dart';
import '../../../core/printer/thermal_printer_manager.dart';
import '../../../l10n/generated/app_localizations.dart';
import '../../../providers/auth_view_model.dart';
import '../../../providers/locale_view_model.dart';
import 'widgets/branch_switcher_dialog.dart';
import 'widgets/printer_settings_dialog.dart';
import 'widgets/sync_log_dialog.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  void _showLogoutDialog(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final authVm = context.read<AuthViewModel>();

    showDialog(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        title: Text(l10n.logoutButton),
        content: const Text('هل أنت متأكد من رغبتك في تسجيل الخروج؟'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogCtx),
            child: Text(l10n.cancel),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: AppColors.error),
            onPressed: () {
              Navigator.pop(dialogCtx);
              authVm.logout();
            },
            child: Text(l10n.logoutButton),
          ),
        ],
      ),
    );
  }

  void _showPrivacyPolicyDialog(BuildContext context) {
    showDialog(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        title: const Row(
          children: [
            Icon(Icons.privacy_tip, color: AppColors.primary),
            SizedBox(width: 8),
            Text('سياسة الخصوصية وأمان البيانات'),
          ],
        ),
        content: const SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                'تلتزم منظومة فهرست (FIHRIST) بأعلى معايير حماية وخصوصية البيانات التجارية والشخصية:',
                style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
              ),
              SizedBox(height: 8),
              Text(
                '• تشفير البيانات: يتم تشفير كافة الاتصالات بين التطبيق وخوادمنا باستخدام بروتوكولات TLS/HTTPS المعتمدة.\n'
                '• الكاميرا: تُستخدم حصرياً لمسح الباركود والـ QR كود للمنتجات والفواتير الضريبية دون تخزين أي صور.\n'
                '• البلوتوث: يُستخدم فقط للاتصال بطابعات الإيصالات الحرارية المعتمدة وملحقات نقاط البيع.\n'
                '• عدم مشاركة البيانات: لا يتم بيع أو مشاركة بيانات مبيعاتك أو عملائك مع أي جهات خارجية إعلانية.\n'
                '• رابط السياسة الكاملة: https://fihrist.world/privacy',
                style: TextStyle(fontSize: 12, height: 1.5),
              ),
            ],
          ),
        ),
        actions: [
          ElevatedButton(
            onPressed: () => Navigator.pop(dialogCtx),
            child: const Text('حسناً'),
          ),
        ],
      ),
    );
  }

  void _showDeleteAccountDialog(BuildContext context) {
    showDialog(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        title: const Row(
          children: [
            Icon(Icons.warning_amber_rounded, color: AppColors.error),
            SizedBox(width: 8),
            Text('طلب حذف الحساب والبيانات'),
          ],
        ),
        content: const Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              'تنبيه: حذف الحساب يؤدي إلى إزالة صلاحيات وصولك وتعطيل حساب المتجر وفق اشتراطات متجر Google Play.',
              style: TextStyle(fontWeight: FontWeight.bold, color: AppColors.error, fontSize: 13),
            ),
            SizedBox(height: 8),
            Text(
              'وفقاً لسياسة حماية البيانات، يمكنك تقديم طلب حذف نهائي لحسابك وبياناتك المسجلة عبر إرسال الطلب، أو زيارة صفحة طلب الحذف الرسمية على:\n'
              'https://fihrist.world/account/delete\n'
              'أو مراسلة الدعم: support@fihrist.world',
              style: TextStyle(fontSize: 12, height: 1.5),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogCtx),
            child: const Text('إلغاء'),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: AppColors.error),
            onPressed: () {
              Navigator.pop(dialogCtx);
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('تم استلام طلب حذف الحساب وسيتم التواصل معك لتأكيده وإتمامه خلال 48 ساعة'),
                  backgroundColor: AppColors.primary,
                ),
              );
            },
            child: const Text('تأكيد الطلب'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final authVm = context.watch<AuthViewModel>();
    final localeVm = context.watch<LocaleViewModel>();
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.settingsTitle),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Store & User Card
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  CircleAvatar(
                    radius: 28,
                    backgroundColor: AppColors.primary.withValues(alpha: 0.15),
                    child: const Icon(
                      Icons.person,
                      size: 32,
                      color: AppColors.primary,
                    ),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          authVm.currentUser?.name ?? 'مسؤول المبيعات',
                          style: const TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          authVm.currentUser?.email ?? 'admin@fihrist.world',
                          style: TextStyle(
                            fontSize: 13,
                            color: isDark
                                ? AppColors.textSecondaryDark
                                : AppColors.textSecondaryLight,
                          ),
                        ),
                        const SizedBox(height: 6),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 8,
                            vertical: 2,
                          ),
                          decoration: BoxDecoration(
                            color: AppColors.primary.withValues(alpha: 0.1),
                            borderRadius: BorderRadius.circular(6),
                          ),
                          child: Text(
                            'المتجر: ${authVm.currentUser?.tenantId ?? "demo"}',
                            style: const TextStyle(
                              fontSize: 11,
                              color: AppColors.primary,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 20),

          // Branch Section
          Text(
            l10n.branchTitle,
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.bold,
              color: isDark
                  ? AppColors.textSecondaryDark
                  : AppColors.textSecondaryLight,
            ),
          ),
          const SizedBox(height: 8),

          Card(
            child: ListTile(
              leading: const Icon(Icons.store, color: AppColors.secondary),
              title: Text(authVm.activeBranch.name),
              subtitle: Text(
                '${authVm.activeBranch.code} • ${authVm.activeBranch.location}',
                style: const TextStyle(fontSize: 12),
              ),
              trailing: ElevatedButton(
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.primary,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  textStyle: const TextStyle(fontSize: 12),
                ),
                onPressed: () {
                  showDialog(
                    context: context,
                    builder: (_) => const BranchSwitcherDialog(),
                  );
                },
                child: Text(l10n.switchBranch),
              ),
            ),
          ),
          const SizedBox(height: 20),

          // Preferences Section
          Text(
            'التفضيلات العامة',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.bold,
              color: isDark
                  ? AppColors.textSecondaryDark
                  : AppColors.textSecondaryLight,
            ),
          ),
          const SizedBox(height: 8),

          Card(
            child: Column(
              children: [
                // Language
                ListTile(
                  leading: const Icon(Icons.language, color: AppColors.primary),
                  title: Text(l10n.language),
                  subtitle: Text(
                    localeVm.isArabic ? l10n.languageArabic : l10n.languageEnglish,
                  ),
                  trailing: TextButton(
                    onPressed: () => localeVm.toggleLanguage(),
                    child: Text(localeVm.isArabic ? 'English' : 'العربية'),
                  ),
                ),
                const Divider(height: 1),

                // Dark mode
                SwitchListTile(
                  secondary: Icon(
                    isDark ? Icons.dark_mode : Icons.light_mode,
                    color: AppColors.primary,
                  ),
                  title: Text(l10n.darkMode),
                  value: localeVm.isDarkMode,
                  onChanged: (_) => localeVm.toggleTheme(),
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),

          // POS Hardware & Printers Section
          Text(
            'عتاد نقطة البيع والطابعات',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.bold,
              color: isDark
                  ? AppColors.textSecondaryDark
                  : AppColors.textSecondaryLight,
            ),
          ),
          const SizedBox(height: 8),

          Card(
            child: Column(
              children: [
                Consumer<ThermalPrinterManager>(
                  builder: (context, printerManager, _) {
                    final isNet = printerManager.config.connectionType == PrinterConnectionType.network;
                    final isBt = printerManager.config.connectionType == PrinterConnectionType.bluetooth;
                    return ListTile(
                      leading: const Icon(Icons.print, color: AppColors.primary),
                      title: const Text('طابعة الفواتير ودرج الكاشير'),
                      subtitle: Text(
                        isNet
                            ? 'طابعة شبكة: ${printerManager.config.deviceAddress}:${printerManager.config.networkPort}'
                            : (isBt
                                ? 'طابعة بلوتوث: ${printerManager.config.deviceName}'
                                : 'معاينة رقمية على الشاشة'),
                        style: const TextStyle(fontSize: 12),
                      ),
                      trailing: const Icon(Icons.tune, size: 20),
                      onTap: () {
                        showDialog(
                          context: context,
                          builder: (_) => const PrinterSettingsDialog(),
                        );
                      },
                    );
                  },
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),

          // Security & Biometrics Section
          Text(
            'الأمان وحماية الجلسة',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.bold,
              color: isDark
                  ? AppColors.textSecondaryDark
                  : AppColors.textSecondaryLight,
            ),
          ),
          const SizedBox(height: 8),

          Card(
            child: Column(
              children: [
                SwitchListTile(
                  secondary: const Icon(Icons.fingerprint, color: AppColors.primary),
                  title: const Text('تسجيل الدخول بالبصمة (Biometrics)'),
                  subtitle: Text(
                    authVm.isBiometricAvailable
                        ? 'الدخول السريع بحساب الكاشير عبر بصمة الإصبع أو الوجه'
                        : 'خاصية البصمة غير مدعومة أو غير مفعلة في جهازك',
                    style: const TextStyle(fontSize: 12),
                  ),
                  value: authVm.isBiometricEnabled,
                  onChanged: authVm.isBiometricAvailable
                      ? (val) async {
                          await authVm.setBiometricEnabled(val);
                        }
                      : null,
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),

          // Notifications Section
          Text(
            'التنبيهات والإشعارات',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.bold,
              color: isDark
                  ? AppColors.textSecondaryDark
                  : AppColors.textSecondaryLight,
            ),
          ),
          const SizedBox(height: 8),

          Card(
            child: Consumer<NotificationService>(
              builder: (context, notifService, _) {
                return Column(
                  children: [
                    SwitchListTile(
                      secondary: const Icon(Icons.notifications_active, color: AppColors.primary),
                      title: const Text('أصوات وتنبيهات الطلبات والرسائل'),
                      subtitle: const Text(
                        'إصدار تنبيه فوري عند وصول رسالة جديدة أو طلب بيع',
                        style: TextStyle(fontSize: 12),
                      ),
                      value: notifService.soundEnabled,
                      onChanged: (val) => notifService.setSoundEnabled(val),
                    ),
                    const Divider(height: 1),
                    SwitchListTile(
                      secondary: const Icon(Icons.vibration, color: AppColors.primary),
                      title: const Text('الاهتزاز اللمسي (Haptic Feedback)'),
                      subtitle: const Text(
                        'اهتزاز عند نجاح العمليات ومسح الباركود',
                        style: TextStyle(fontSize: 12),
                      ),
                      value: notifService.vibrationEnabled,
                      onChanged: (val) => notifService.setVibrationEnabled(val),
                    ),
                  ],
                );
              },
            ),
          ),
          const SizedBox(height: 20),

          // System Info Section
          Text(
            'عن النظام',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.bold,
              color: isDark
                  ? AppColors.textSecondaryDark
                  : AppColors.textSecondaryLight,
            ),
          ),
          const SizedBox(height: 8),

          Card(
            child: Column(
              children: [
                const ListTile(
                  leading: Icon(Icons.info_outline, color: AppColors.secondary),
                  title: Text('إصدار التطبيق'),
                  trailing: Text('1.0.0 (v0.2.0-mobile)'),
                ),
                const Divider(height: 1),
                ListTile(
                  leading: const Icon(Icons.cloud_sync, color: AppColors.primary),
                  title: const Text('سجل المزامنة والعمليات دون إنترنت'),
                  subtitle: const Text('عرض الطابور وحل التعارضات (Conflicts)', style: TextStyle(fontSize: 12)),
                  trailing: const Icon(Icons.chevron_left),
                  onTap: () {
                    showDialog(
                      context: context,
                      builder: (_) => const SyncLogDialog(),
                    );
                  },
                ),
                const Divider(height: 1),
                ListTile(
                  leading: const Icon(Icons.privacy_tip_outlined, color: AppColors.primary),
                  title: const Text('سياسة الخصوصية وأمان البيانات'),
                  subtitle: const Text('معايير تشفير وحماية البيانات المعتمدة', style: TextStyle(fontSize: 12)),
                  trailing: const Icon(Icons.chevron_left),
                  onTap: () => _showPrivacyPolicyDialog(context),
                ),
                const Divider(height: 1),
                ListTile(
                  leading: const Icon(Icons.person_remove_outlined, color: AppColors.error),
                  title: const Text('طلب حذف الحساب والبيانات'),
                  subtitle: const Text('تقديم طلب لحذف الحساب نهائياً وفق اشتراطات جوجل', style: TextStyle(fontSize: 12)),
                  trailing: const Icon(Icons.chevron_left),
                  onTap: () => _showDeleteAccountDialog(context),
                ),
              ],
            ),
          ),
          const SizedBox(height: 28),

          // Logout Button
          ElevatedButton.icon(
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.error,
              foregroundColor: Colors.white,
            ),
            icon: const Icon(Icons.logout),
            label: Text(l10n.logoutButton),
            onPressed: () => _showLogoutDialog(context),
          ),
        ],
      ),
    );
  }
}
