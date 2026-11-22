import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../core/constants/app_colors.dart';
import '../../../core/notifications/notification_service.dart';
import '../../../core/utils/money_formatter.dart';
import '../../../l10n/generated/app_localizations.dart';
import '../../../providers/auth_view_model.dart';
import '../../../providers/dashboard_view_model.dart';
import '../../../providers/locale_view_model.dart';
import '../purchasing/purchasing_screen.dart';
import '../reports/reports_screen.dart';

class DashboardScreen extends StatelessWidget {
  const DashboardScreen({super.key});

  void _showNotificationsSheet(BuildContext context) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => Consumer<NotificationService>(
        builder: (ctx, notifService, _) {
          final alerts = notifService.alerts;
          final isDark = Theme.of(ctx).brightness == Brightness.dark;

          return ConstrainedBox(
            constraints: BoxConstraints(
              maxHeight: MediaQuery.of(ctx).size.height * 0.7,
            ),
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Row(
                        children: [
                          const Icon(Icons.notifications_active, color: AppColors.primary),
                          const SizedBox(width: 8),
                          const Text(
                            'التنبيهات والإشعارات',
                            style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                          ),
                          if (notifService.unreadCount > 0) ...[
                            const SizedBox(width: 8),
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                              decoration: BoxDecoration(
                                color: AppColors.primary,
                                borderRadius: BorderRadius.circular(10),
                              ),
                              child: Text(
                                '${notifService.unreadCount}',
                                style: const TextStyle(color: Colors.white, fontSize: 12),
                              ),
                            ),
                          ],
                        ],
                      ),
                      if (alerts.isNotEmpty)
                        TextButton(
                          onPressed: () => notifService.markAllAsRead(),
                          child: const Text('قراءة الكل'),
                        ),
                    ],
                  ),
                  const Divider(height: 16),
                  Expanded(
                    child: alerts.isEmpty
                        ? Center(
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Icon(Icons.notifications_none, size: 48, color: Colors.grey[400]),
                                const SizedBox(height: 8),
                                Text(
                                  'لا توجد إشعارات جديدة حالياً',
                                  style: TextStyle(color: isDark ? Colors.grey[400] : Colors.grey[600]),
                                ),
                              ],
                            ),
                          )
                        : ListView.separated(
                            itemCount: alerts.length,
                            separatorBuilder: (_, __) => const Divider(height: 8),
                            itemBuilder: (context, i) {
                              final alert = alerts[i];
                              return ListTile(
                                dense: true,
                                contentPadding: EdgeInsets.zero,
                                leading: CircleAvatar(
                                  radius: 16,
                                  backgroundColor: alert.isRead
                                      ? Colors.grey.withValues(alpha: 0.15)
                                      : AppColors.primary.withValues(alpha: 0.15),
                                  child: Icon(
                                    alert.type == NotificationType.newMessage
                                        ? Icons.chat
                                        : alert.type == NotificationType.newOrder
                                            ? Icons.shopping_bag
                                            : Icons.info,
                                    size: 16,
                                    color: alert.isRead ? Colors.grey : AppColors.primary,
                                  ),
                                ),
                                title: Text(
                                  alert.title,
                                  style: TextStyle(
                                    fontWeight: alert.isRead ? FontWeight.normal : FontWeight.bold,
                                    fontSize: 13,
                                  ),
                                ),
                                subtitle: Text(
                                  alert.body,
                                  style: const TextStyle(fontSize: 11),
                                ),
                                trailing: Text(
                                  '${alert.timestamp.hour.toString().padLeft(2, '0')}:${alert.timestamp.minute.toString().padLeft(2, '0')}',
                                  style: const TextStyle(fontSize: 10, color: Colors.grey),
                                ),
                                onTap: () => notifService.markAsRead(alert.id),
                              );
                            },
                          ),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final dashboardVm = context.watch<DashboardViewModel>();
    final authVm = context.watch<AuthViewModel>();
    final localeVm = context.watch<LocaleViewModel>();
    final isDark = Theme.of(context).brightness == Brightness.dark;

    final stats = dashboardVm.stats;

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.dashboardTitle),
        actions: [
          Consumer<NotificationService>(
            builder: (context, notif, _) {
              return IconButton(
                icon: notif.unreadCount > 0
                    ? Badge(
                        label: Text('${notif.unreadCount}'),
                        child: const Icon(Icons.notifications_outlined),
                      )
                    : const Icon(Icons.notifications_outlined),
                onPressed: () => _showNotificationsSheet(context),
                tooltip: 'التنبيهات',
              );
            },
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => dashboardVm.refresh(),
            tooltip: l10n.retry,
          ),
          IconButton(
            icon: Icon(isDark ? Icons.light_mode : Icons.dark_mode),
            onPressed: () => localeVm.toggleTheme(),
            tooltip: l10n.darkMode,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => dashboardVm.refresh(),
        child: dashboardVm.isLoading && stats == null
            ? const Center(child: CircularProgressIndicator())
            : SingleChildScrollView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Store & User Greeting Header
                    Container(
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        gradient: LinearGradient(
                          colors: [
                            AppColors.primary,
                            AppColors.primaryDark,
                          ],
                          begin: Alignment.topLeft,
                          end: Alignment.bottomRight,
                        ),
                        borderRadius: BorderRadius.circular(16),
                      ),
                      child: Row(
                        children: [
                          CircleAvatar(
                            backgroundColor: Colors.white.withValues(alpha: 0.2),
                            radius: 26,
                            child: const Icon(
                              Icons.storefront,
                              color: Colors.white,
                              size: 28,
                            ),
                          ),
                          const SizedBox(width: 14),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  authVm.currentUser?.name ??
                                      authVm.currentUser?.tenantName ??
                                      l10n.appTitle,
                                  style: const TextStyle(
                                    color: Colors.white,
                                    fontSize: 18,
                                    fontWeight: FontWeight.bold,
                                  ),
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  authVm.currentUser?.email ?? 'sales@fihrist.world',
                                  style: TextStyle(
                                    color: Colors.white.withValues(alpha: 0.85),
                                    fontSize: 13,
                                  ),
                                ),
                                const SizedBox(height: 6),
                                Container(
                                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                                  decoration: BoxDecoration(
                                    color: Colors.white.withValues(alpha: 0.2),
                                    borderRadius: BorderRadius.circular(10),
                                  ),
                                  child: Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      const Icon(Icons.store, color: Colors.white, size: 12),
                                      const SizedBox(width: 4),
                                      Text(
                                        authVm.activeBranch.name,
                                        style: const TextStyle(
                                          color: Colors.white,
                                          fontSize: 11,
                                          fontWeight: FontWeight.w500,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 20),

                    // Metrics Grid (2x2)
                    GridView.count(
                      crossAxisCount: 2,
                      crossAxisSpacing: 12,
                      mainAxisSpacing: 12,
                      childAspectRatio: 1.45,
                      shrinkWrap: true,
                      physics: const NeverScrollableScrollPhysics(),
                      children: [
                        _buildMetricCard(
                          context,
                          title: l10n.todaySales,
                          value: MoneyFormatter.format(
                            stats?.todaySales,
                            currency: l10n.currencySar,
                          ),
                          icon: Icons.payments_outlined,
                          color: AppColors.primary,
                          isDark: isDark,
                        ),
                        _buildMetricCard(
                          context,
                          title: l10n.todayOrders,
                          value: stats?.todayOrdersCount.toString() ?? '0',
                          icon: Icons.shopping_bag_outlined,
                          color: AppColors.secondary,
                          isDark: isDark,
                        ),
                        _buildMetricCard(
                          context,
                          title: l10n.averageOrderValue,
                          value: MoneyFormatter.format(
                            stats?.averageOrderValue,
                            currency: l10n.currencySar,
                          ),
                          icon: Icons.analytics_outlined,
                          color: AppColors.info,
                          isDark: isDark,
                        ),
                        _buildMetricCard(
                          context,
                          title: l10n.lowStockAlerts,
                          value: stats?.lowStockCount.toString() ?? '0',
                          icon: Icons.warning_amber_rounded,
                          color: AppColors.warning,
                          isDark: isDark,
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),

                    // Quick Operations: Purchasing & Suppliers
                    Card(
                      elevation: 0,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                        side: BorderSide(
                          color: isDark ? Colors.white12 : Colors.grey.shade200,
                        ),
                      ),
                      child: ListTile(
                        leading: CircleAvatar(
                          backgroundColor: AppColors.secondary.withValues(alpha: 0.15),
                          child: const Icon(Icons.local_shipping_outlined, color: AppColors.secondary),
                        ),
                        title: const Text(
                          'المشتريات والموردون',
                          style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
                        ),
                        subtitle: const Text(
                          'متابعة أوامر الشراء، استلام الشحنات، ومطابقة الكميات',
                          style: TextStyle(fontSize: 12),
                        ),
                        trailing: const Icon(Icons.arrow_forward_ios, size: 14),
                        onTap: () {
                          Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (_) => const PurchasingScreen(),
                            ),
                          );
                        },
                      ),
                    ),
                    const SizedBox(height: 10),

                    // Quick Operations: Reports & Analytics
                    Card(
                      elevation: 0,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                        side: BorderSide(
                          color: isDark ? Colors.white12 : Colors.grey.shade200,
                        ),
                      ),
                      child: ListTile(
                        leading: CircleAvatar(
                          backgroundColor: AppColors.primary.withValues(alpha: 0.15),
                          child: const Icon(Icons.analytics_outlined, color: AppColors.primary),
                        ),
                        title: const Text(
                          'التقارير والتحليلات المالية',
                          style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
                        ),
                        subtitle: const Text(
                          'تقارير المبيعات، المخزون الراكد، مطابقة الصندوق، وتوصيات الذكاء',
                          style: TextStyle(fontSize: 12),
                        ),
                        trailing: const Icon(Icons.arrow_forward_ios, size: 14),
                        onTap: () {
                          Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (_) => const ReportsScreen(),
                            ),
                          );
                        },
                      ),
                    ),
                    const SizedBox(height: 20),

                    // Recent Orders Section Header
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(
                          l10n.recentOrders,
                          style: Theme.of(context).textTheme.titleMedium?.copyWith(
                                fontWeight: FontWeight.bold,
                              ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),

                    // Recent Orders List
                    if (stats != null && stats.recentOrders.isNotEmpty)
                      ListView.separated(
                        shrinkWrap: true,
                        physics: const NeverScrollableScrollPhysics(),
                        itemCount: stats.recentOrders.length,
                        separatorBuilder: (_, __) => const SizedBox(height: 8),
                        itemBuilder: (context, index) {
                          final order = stats.recentOrders[index];
                          return Card(
                            child: ListTile(
                              leading: CircleAvatar(
                                backgroundColor: _getStatusColor(order.status)
                                    .withValues(alpha: 0.15),
                                child: Icon(
                                  _getChannelIcon(order.channel),
                                  color: _getStatusColor(order.status),
                                  size: 20,
                                ),
                              ),
                              title: Text(
                                order.orderNumber,
                                style: const TextStyle(fontWeight: FontWeight.bold),
                              ),
                              subtitle: Text(
                                order.customerName ?? 'عميل نقطة البيع',
                              ),
                              trailing: Column(
                                mainAxisAlignment: MainAxisAlignment.center,
                                crossAxisAlignment: CrossAxisAlignment.end,
                                children: [
                                  Text(
                                    MoneyFormatter.format(
                                      order.totalAmount,
                                      currency: l10n.currencySar,
                                    ),
                                    style: const TextStyle(
                                      fontWeight: FontWeight.bold,
                                      fontSize: 14,
                                    ),
                                  ),
                                  const SizedBox(height: 4),
                                  Container(
                                    padding: const EdgeInsets.symmetric(
                                      horizontal: 6,
                                      vertical: 2,
                                    ),
                                    decoration: BoxDecoration(
                                      color: _getStatusColor(order.status)
                                          .withValues(alpha: 0.12),
                                      borderRadius: BorderRadius.circular(4),
                                    ),
                                    child: Text(
                                      _getStatusLabel(context, order.status),
                                      style: TextStyle(
                                        color: _getStatusColor(order.status),
                                        fontSize: 11,
                                        fontWeight: FontWeight.w600,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          );
                        },
                      )
                    else
                      Center(
                        child: Padding(
                          padding: const EdgeInsets.symmetric(vertical: 24),
                          child: Text(
                            l10n.emptyCart,
                            style: const TextStyle(color: Colors.grey),
                          ),
                        ),
                      ),
                  ],
                ),
              ),
      ),
    );
  }

  Widget _buildMetricCard(
    BuildContext context, {
    required String title,
    required String value,
    required IconData icon,
    required Color color,
    required bool isDark,
  }) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Expanded(
                  child: Text(
                    title,
                    style: TextStyle(
                      fontSize: 12,
                      color: isDark
                          ? AppColors.textSecondaryDark
                          : AppColors.textSecondaryLight,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                Container(
                  padding: const EdgeInsets.all(6),
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Icon(icon, color: color, size: 18),
                ),
              ],
            ),
            Text(
              value,
              style: const TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.bold,
              ),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ],
        ),
      ),
    );
  }

  Color _getStatusColor(String status) {
    switch (status.toLowerCase()) {
      case 'completed':
        return AppColors.success;
      case 'pending':
        return AppColors.warning;
      case 'cancelled':
        return AppColors.error;
      default:
        return AppColors.info;
    }
  }

  String _getStatusLabel(BuildContext context, String status) {
    final l10n = AppLocalizations.of(context)!;
    switch (status.toLowerCase()) {
      case 'completed':
        return l10n.orderStatusCompleted;
      case 'pending':
        return l10n.orderStatusPending;
      case 'cancelled':
        return l10n.orderStatusCancelled;
      default:
        return status;
    }
  }

  IconData _getChannelIcon(String channel) {
    switch (channel.toLowerCase()) {
      case 'whatsapp':
        return Icons.chat;
      case 'instagram':
        return Icons.camera_alt;
      case 'telegram':
        return Icons.send;
      default:
        return Icons.point_of_sale;
    }
  }
}
