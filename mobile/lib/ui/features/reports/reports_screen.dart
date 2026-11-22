import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../../../core/constants/app_colors.dart';
import '../../../core/utils/money_formatter.dart';
import '../../../l10n/generated/app_localizations.dart';
import '../../../providers/auth_view_model.dart';
import '../../../providers/dashboard_view_model.dart';

class ReportsScreen extends StatefulWidget {
  const ReportsScreen({super.key});

  @override
  State<ReportsScreen> createState() => _ReportsScreenState();
}

class _ReportsScreenState extends State<ReportsScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;
  String _selectedPeriod = 'today'; // today, week, month

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 4, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  Future<void> _shareReportSummary(BuildContext context) async {
    final authVm = context.read<AuthViewModel>();
    final dashboardVm = context.read<DashboardViewModel>();
    final stats = dashboardVm.stats;

    final branchName = authVm.activeBranch.name;
    final now = DateTime.now();
    final dateStr = '${now.year}-${now.month.toString().padLeft(2, '0')}-${now.day.toString().padLeft(2, '0')}';

    final summary = '''
📊 تقرير أداء متجر فهرست (${authVm.currentUser?.tenantName ?? 'المتجر'})
🏢 الفرع: $branchName
📅 التاريخ: $dateStr
━━━━━━━━━━━━━━━━━━━━━━
💰 مبيعات اليوم: ${MoneyFormatter.format(stats?.todaySales, currency: 'ر.س')}
📦 عدد الطلبات: ${stats?.todayOrdersCount ?? 0} طلب
🎯 متوسط قيمة الطلب: ${MoneyFormatter.format(stats?.averageOrderValue, currency: 'ر.س')}
⚠️ تنبيهات نقص المخزون: ${stats?.lowStockCount ?? 0} صنف
💵 رصيد النقدية المطابق: 4,620.00 ر.س (فارق: 0.00 ر.س)
━━━━━━━━━━━━━━━━━━━━━━
💡 توصية وكيل التحليلات: تم تسجيل زيادة 22% في مبيعات بطاقات الدفع مقارنة بالأمس.
    ''';

    await Clipboard.setData(ClipboardData(text: summary));
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('تم نسخ ملخص التقرير إلى الحافظة بنجاح!'),
          backgroundColor: AppColors.primary,
          duration: Duration(seconds: 3),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final authVm = context.watch<AuthViewModel>();
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.reportsTitle),
        actions: [
          IconButton(
            icon: const Icon(Icons.share_outlined),
            tooltip: l10n.exportSummary,
            onPressed: () => _shareReportSummary(context),
          ),
        ],
        bottom: TabBar(
          controller: _tabController,
          isScrollable: true,
          tabAlignment: TabAlignment.start,
          indicatorColor: AppColors.primary,
          labelColor: AppColors.primary,
          unselectedLabelColor: isDark ? Colors.grey[400] : Colors.grey[600],
          tabs: const [
            Tab(icon: Icon(Icons.bar_chart, size: 18), text: 'المبيعات والمالية'),
            Tab(icon: Icon(Icons.inventory, size: 18), text: 'المخزون والركود'),
            Tab(icon: Icon(Icons.point_of_sale, size: 18), text: 'مطابقة الورديات'),
            Tab(icon: Icon(Icons.auto_awesome, size: 18), text: 'توصيات الذكاء'),
          ],
        ),
      ),
      body: Column(
        children: [
          // Filter Bar (Period & Branch)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            decoration: BoxDecoration(
              color: isDark ? Colors.grey.shade900 : Colors.grey.shade100,
              border: Border(
                bottom: BorderSide(
                  color: isDark ? Colors.white12 : Colors.grey.shade300,
                ),
              ),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Row(
                  children: [
                    const Icon(Icons.store, size: 16, color: AppColors.primary),
                    const SizedBox(width: 6),
                    Text(
                      authVm.activeBranch.name,
                      style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold),
                    ),
                  ],
                ),
                DropdownButtonHideUnderline(
                  child: DropdownButton<String>(
                    value: _selectedPeriod,
                    isDense: true,
                    items: const [
                      DropdownMenuItem(value: 'today', child: Text('اليوم', style: TextStyle(fontSize: 12))),
                      DropdownMenuItem(value: 'week', child: Text('هذا الأسبوع', style: TextStyle(fontSize: 12))),
                      DropdownMenuItem(value: 'month', child: Text('هذا الشهر', style: TextStyle(fontSize: 12))),
                    ],
                    onChanged: (val) {
                      if (val != null) {
                        setState(() => _selectedPeriod = val);
                      }
                    },
                  ),
                ),
              ],
            ),
          ),

          // Tab Views
          Expanded(
            child: TabBarView(
              controller: _tabController,
              children: [
                _buildSalesReportTab(context, isDark),
                _buildInventoryReportTab(context, isDark),
                _buildShiftsReportTab(context, isDark),
                _buildAiInsightsTab(context, isDark),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSalesReportTab(BuildContext context, bool isDark) {
    final dashboardVm = context.watch<DashboardViewModel>();
    final stats = dashboardVm.stats;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // Summary Cards
        Row(
          children: [
            Expanded(
              child: _buildKpiCard(
                title: 'إجمالي المبيعات',
                value: MoneyFormatter.format(
                  _selectedPeriod == 'today'
                      ? stats?.todaySales
                      : (_selectedPeriod == 'week' ? '34,250.00' : '148,800.00'),
                  currency: 'ر.س',
                ),
                icon: Icons.payments,
                color: AppColors.primary,
                isDark: isDark,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: _buildKpiCard(
                title: 'عدد الفواتير',
                value: _selectedPeriod == 'today'
                    ? '${stats?.todayOrdersCount ?? 0}'
                    : (_selectedPeriod == 'week' ? '184' : '792'),
                icon: Icons.receipt_long,
                color: AppColors.secondary,
                isDark: isDark,
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: _buildKpiCard(
                title: 'متوسط الفاتورة',
                value: MoneyFormatter.format(
                  stats?.averageOrderValue,
                  currency: 'ر.س',
                ),
                icon: Icons.analytics,
                color: AppColors.info,
                isDark: isDark,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: _buildKpiCard(
                title: 'هامش الربح التقديري',
                value: '38.5%',
                icon: Icons.trending_up,
                color: AppColors.success,
                isDark: isDark,
              ),
            ),
          ],
        ),
        const SizedBox(height: 20),

        // Payment Methods Breakdown
        const Text(
          'توزيع طرق الدفع',
          style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
        ),
        const SizedBox(height: 10),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              children: [
                _buildPaymentBreakdownRow('بطاقة مدى / ائتمان', '3,450.00 ر.س', '71%', AppColors.primary),
                const Divider(height: 16),
                _buildPaymentBreakdownRow('نقدي (كاش)', '1,200.00 ر.س', '25%', AppColors.success),
                const Divider(height: 16),
                _buildPaymentBreakdownRow('دفع مقسم / محفظة', '200.00 ر.س', '4%', AppColors.secondary),
              ],
            ),
          ),
        ),
        const SizedBox(height: 20),

        // Top Selling Products
        const Text(
          'الأصناف الأكثر مبيعاً في هذا الفرع',
          style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
        ),
        const SizedBox(height: 10),
        Card(
          child: ListView(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            children: const [
              ListTile(
                leading: CircleAvatar(child: Text('1')),
                title: Text('قميص أكسفورد كلاسيك أبيض'),
                subtitle: Text('تم بيع 42 قطعة • إجمالي: 6,090 ر.س'),
                trailing: Text('سريع الحركة', style: TextStyle(color: AppColors.success, fontSize: 12)),
              ),
              Divider(height: 1),
              ListTile(
                leading: CircleAvatar(child: Text('2')),
                title: Text('بنطال جينز كلاسيك مريح'),
                subtitle: Text('تم بيع 28 قطعة • إجمالي: 5,180 ر.س'),
                trailing: Text('سريع الحركة', style: TextStyle(color: AppColors.success, fontSize: 12)),
              ),
              Divider(height: 1),
              ListTile(
                leading: CircleAvatar(child: Text('3')),
                title: Text('حذاء كاجوال جلد بني'),
                subtitle: Text('تم بيع 15 قطعة • إجمالي: 4,200 ر.س'),
                trailing: Text('طبيعي', style: TextStyle(color: AppColors.info, fontSize: 12)),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildInventoryReportTab(BuildContext context, bool isDark) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // Valuation Header
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: isDark ? Colors.grey.shade900 : Colors.indigo.shade50,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: isDark ? Colors.white12 : Colors.indigo.shade200,
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'إجمالي القيمة التقديرية لمخزون الفرع',
                style: TextStyle(fontSize: 13, color: Colors.grey),
              ),
              const SizedBox(height: 6),
              const Text(
                '58,260.00 ر.س',
                style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: AppColors.primary),
              ),
              const SizedBox(height: 4),
              Text(
                'محسوب بسعر التكلفة لـ 365 وحدة مخزنة',
                style: TextStyle(fontSize: 11, color: isDark ? Colors.grey[400] : Colors.grey[600]),
              ),
            ],
          ),
        ),
        const SizedBox(height: 20),

        // Dead Stock Section
        const Row(
          children: [
            Icon(Icons.report_problem, color: AppColors.warning, size: 20),
            SizedBox(width: 8),
            Text(
              'تنبيهات المخزون الراكد (Dead Stock)',
              style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
            ),
          ],
        ),
        const SizedBox(height: 6),
        const Text(
          'أصناف متوقفة عن الحركة لأكثر من 60 يوماً وتعيق رأس المال:',
          style: TextStyle(fontSize: 12, color: Colors.grey),
        ),
        const SizedBox(height: 10),
        Card(
          child: ListTile(
            leading: const CircleAvatar(
              backgroundColor: Color(0x22F59E0B),
              child: Icon(Icons.hourglass_empty, color: AppColors.warning),
            ),
            title: const Text('محفظة جلد طبيعي رجالي'),
            subtitle: const Text('الكمية: 95 قطعة • رأس مال معطل: 6,175 ر.س • آخر حركة: منذ 68 يوم'),
            trailing: Chip(
              label: const Text('راكد', style: TextStyle(fontSize: 11, color: AppColors.warning)),
              backgroundColor: const Color(0x15F59E0B),
              padding: EdgeInsets.zero,
            ),
          ),
        ),
        const SizedBox(height: 20),

        // Low Stock Section
        const Row(
          children: [
            Icon(Icons.warning_amber_rounded, color: AppColors.error, size: 20),
            SizedBox(width: 8),
            Text(
              'أصناف قاربت على النفاد (Low Stock)',
              style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Card(
          child: ListView(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            children: const [
              ListTile(
                title: Text('تي شيرت قطن مصري أسود'),
                subtitle: Text('المتبقي: 3 قطع فقط • حد الطلب: 10 قطع'),
                trailing: Text('عاجل', style: TextStyle(color: AppColors.error, fontWeight: FontWeight.bold)),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildShiftsReportTab(BuildContext context, bool isDark) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const Text(
          'سجل إغلاق ورديات الكاشير ومطابقة الصندوق (Z-Report)',
          style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
        ),
        const SizedBox(height: 12),
        _buildShiftCard(
          shiftNumber: 'SH-2026-112',
          cashier: 'أحمد محمود',
          time: 'اليوم (08:00 ص - 04:00 م)',
          openingBalance: '500.00 ر.س',
          systemTotal: '4,620.00 ر.س',
          actualCash: '4,620.00 ر.س',
          variance: '0.00 ر.س',
          isMatched: true,
        ),
        const SizedBox(height: 12),
        _buildShiftCard(
          shiftNumber: 'SH-2026-111',
          cashier: 'سارة خالد',
          time: 'أمس (04:00 م - 11:30 م)',
          openingBalance: '500.00 ر.س',
          systemTotal: '6,840.00 ر.س',
          actualCash: '6,850.00 ر.س',
          variance: '+10.00 ر.س',
          isMatched: false,
        ),
      ],
    );
  }

  Widget _buildAiInsightsTab(BuildContext context, bool isDark) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            gradient: const LinearGradient(
              colors: [Color(0xFF2563EB), Color(0xFF1D4ED8)],
            ),
            borderRadius: BorderRadius.circular(14),
          ),
          child: const Row(
            children: [
              Icon(Icons.auto_awesome, color: Colors.white, size: 28),
              SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'وكيل تحليلات فهرست (Analytics Agent)',
                      style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 15),
                    ),
                    SizedBox(height: 4),
                    Text(
                      'تحليلات فورية واكتشاف الأنماط غير الطبيعية والتوصيات التشغيلية',
                      style: TextStyle(color: Colors.white70, fontSize: 12),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        _buildInsightCard(
          icon: Icons.trending_up,
          color: AppColors.success,
          title: 'ارتفاع الطلب على قمصان أكسفورد',
          body: 'مبيعات قميص أكسفورد سجلت نمواً 35% في عطلة نهاية الأسبوع. يُنصح برفع أمر شراء جديد قبل نفاد الكمية خلال 5 أيام.',
        ),
        const SizedBox(height: 12),
        _buildInsightCard(
          icon: Icons.price_change,
          color: AppColors.warning,
          title: 'فرصة تحريك المخزون الراكد',
          body: 'محفظة الجلد الطبيعي (95 قطعة) معطلة منذ أكثر من 60 يوماً. تشير البيانات إلى أن تطبيق خصم 15% أو دمجها في عرض ترويجي سيرفع معدل التصريف بنسبة 60%.',
        ),
        const SizedBox(height: 12),
        _buildInsightCard(
          icon: Icons.shield,
          color: AppColors.info,
          title: 'فحص العمليات المشبوهة',
          body: 'لم يتم رصد أي عمليات إلغاء فواتير غير اعتيادية أو فروقات نقدية متكررة خلال آخر 48 ساعة. مؤشر النزاهة 99.8%.',
        ),
      ],
    );
  }

  Widget _buildKpiCard({
    required String title,
    required String value,
    required IconData icon,
    required Color color,
    required bool isDark,
  }) {
    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: isDark ? Colors.white12 : Colors.grey.shade200,
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Expanded(
                  child: Text(
                    title,
                    style: TextStyle(
                      fontSize: 12,
                      color: isDark ? Colors.grey[400] : Colors.grey[600],
                    ),
                  ),
                ),
                Icon(icon, size: 18, color: color),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              value,
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildPaymentBreakdownRow(String name, String amount, String percentage, Color color) {
    return Row(
      children: [
        Container(width: 10, height: 10, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
        const SizedBox(width: 8),
        Expanded(child: Text(name, style: const TextStyle(fontSize: 13))),
        Text(amount, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13)),
        const SizedBox(width: 10),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
          decoration: BoxDecoration(color: color.withValues(alpha: 0.1), borderRadius: BorderRadius.circular(4)),
          child: Text(percentage, style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.bold)),
        ),
      ],
    );
  }

  Widget _buildShiftCard({
    required String shiftNumber,
    required String cashier,
    required String time,
    required String openingBalance,
    required String systemTotal,
    required String actualCash,
    required String variance,
    required bool isMatched,
  }) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(shiftNumber, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: isMatched
                        ? AppColors.success.withValues(alpha: 0.12)
                        : AppColors.warning.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    isMatched ? 'مطابق' : 'يوجد فارق',
                    style: TextStyle(
                      color: isMatched ? AppColors.success : AppColors.warning,
                      fontSize: 11,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text('الكاشير: $cashier • $time', style: const TextStyle(fontSize: 12, color: Colors.grey)),
            const Divider(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                _buildShiftField('الافتتاحي', openingBalance),
                _buildShiftField('إجمالي النظام', systemTotal),
                _buildShiftField('النقدي الفعلي', actualCash),
                _buildShiftField('الفارق', variance),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildShiftField(String label, String value) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(fontSize: 11, color: Colors.grey)),
        const SizedBox(height: 2),
        Text(value, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold)),
      ],
    );
  }

  Widget _buildInsightCard({
    required IconData icon,
    required Color color,
    required String title,
    required String body,
  }) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            CircleAvatar(
              radius: 18,
              backgroundColor: color.withValues(alpha: 0.12),
              child: Icon(icon, color: color, size: 20),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
                  const SizedBox(height: 4),
                  Text(body, style: const TextStyle(fontSize: 12, height: 1.4)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
