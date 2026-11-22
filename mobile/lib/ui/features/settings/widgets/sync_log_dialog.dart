import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../../core/constants/app_colors.dart';
import '../../../../core/sync/durable_operation.dart';
import '../../../../core/sync/durable_sync_engine.dart';
import '../../../../providers/auth_view_model.dart';

class SyncLogDialog extends StatefulWidget {
  const SyncLogDialog({super.key});

  @override
  State<SyncLogDialog> createState() => _SyncLogDialogState();
}

class _SyncLogDialogState extends State<SyncLogDialog> {
  final DurableSyncEngine _syncEngine = DurableSyncEngine();
  List<DurableOperation> _operations = [];
  bool _isLoading = true;
  bool _isSyncing = false;
  String _filter = 'all'; // 'all', 'pending', 'conflict', 'acknowledged'

  @override
  void initState() {
    super.initState();
    _loadOperations();
  }

  Future<void> _loadOperations() async {
    setState(() => _isLoading = true);
    final tenantId = context.read<AuthViewModel>().currentUser?.tenantId;
    if (tenantId == null || tenantId.isEmpty) {
      if (mounted) {
        setState(() {
          _operations = [];
          _isLoading = false;
        });
      }
      return;
    }
    final ops = await _syncEngine.getAllOperations(tenantId: tenantId);
    if (mounted) {
      setState(() {
        _operations = ops;
        _isLoading = false;
      });
    }
  }

  Future<void> _triggerSync() async {
    final tenantId = context.read<AuthViewModel>().currentUser?.tenantId;
    if (tenantId == null || tenantId.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('يرجى تسجيل الدخول واختيار المتجر قبل المزامنة لضمان عزل البيانات'),
          backgroundColor: AppColors.warning,
        ),
      );
      return;
    }
    setState(() => _isSyncing = true);
    final result = await _syncEngine.syncPendingOperations(tenantId: tenantId);
    await _loadOperations();
    if (mounted) {
      setState(() => _isSyncing = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'نتائج المزامنة: ${result.successCount} نجاح، ${result.conflictCount} تعارض، ${result.failedCount} فشل',
          ),
          backgroundColor: result.conflictCount > 0 ? AppColors.warning : AppColors.success,
        ),
      );
    }
  }

  Future<void> _retryOperation(String uuid) async {
    final tenantId = context.read<AuthViewModel>().currentUser?.tenantId;
    await _syncEngine.retryOperation(uuid, tenantId: tenantId);
    await _loadOperations();
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('تمت إعادة جدولة العملية للمزامنة القادمة'),
          duration: Duration(seconds: 2),
        ),
      );
    }
  }

  Future<void> _discardOperation(String uuid) async {
    final tenantId = context.read<AuthViewModel>().currentUser?.tenantId;
    await _syncEngine.discardOperation(uuid, tenantId: tenantId);
    await _loadOperations();
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('تم حذف العملية من الطابور المحلي'),
          duration: Duration(seconds: 2),
        ),
      );
    }
  }

  List<DurableOperation> get _filteredOperations {
    if (_filter == 'pending') {
      return _operations.where((op) => op.status == DurableOperationStatus.pending || op.status == DurableOperationStatus.sending).toList();
    }
    if (_filter == 'conflict') {
      return _operations.where((op) => op.status == DurableOperationStatus.conflict).toList();
    }
    if (_filter == 'acknowledged') {
      return _operations.where((op) => op.status == DurableOperationStatus.acknowledged).toList();
    }
    return _operations;
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final conflictCount = _operations.where((op) => op.status == DurableOperationStatus.conflict).length;
    final pendingCount = _operations.where((op) => op.status == DurableOperationStatus.pending || op.status == DurableOperationStatus.sending).length;

    return Dialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 500, maxHeight: 680),
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Header
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.all(8),
                        decoration: BoxDecoration(
                          color: AppColors.primary.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: const Icon(Icons.sync_alt, color: AppColors.primary, size: 24),
                      ),
                      const SizedBox(width: 10),
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            'سجل المزامنة والعمليات',
                            style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                          ),
                          Text(
                            'طابور العمليات غير المتصلة وإدارة التعارضات',
                            style: TextStyle(
                              fontSize: 11,
                              color: isDark ? Colors.grey[400] : Colors.grey[600],
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                  IconButton(
                    icon: const Icon(Icons.close),
                    onPressed: () => Navigator.pop(context),
                  ),
                ],
              ),
              const Divider(height: 20),

              // Summary & Sync Now button
              Row(
                children: [
                  Expanded(
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                      decoration: BoxDecoration(
                        color: isDark ? AppColors.surfaceDark : Colors.grey.withValues(alpha: 0.08),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.spaceAround,
                        children: [
                          Text('معلق: $pendingCount', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
                          Text(
                            'تعارض: $conflictCount',
                            style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.bold,
                              color: conflictCount > 0 ? Colors.red : null,
                            ),
                          ),
                          Text('إجمالي: ${_operations.length}', style: const TextStyle(fontSize: 12)),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  ElevatedButton.icon(
                    style: ElevatedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                    ),
                    icon: _isSyncing
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                          )
                        : const Icon(Icons.refresh, size: 16),
                    label: const Text('مزامنة الآن', style: TextStyle(fontSize: 12)),
                    onPressed: _isSyncing ? null : _triggerSync,
                  ),
                ],
              ),
              const SizedBox(height: 12),

              // Filter Chips
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  children: [
                    FilterChip(
                      label: Text('الكل (${_operations.length})'),
                      selected: _filter == 'all',
                      onSelected: (_) => setState(() => _filter = 'all'),
                    ),
                    const SizedBox(width: 6),
                    FilterChip(
                      label: Text('معلق ($pendingCount)'),
                      selected: _filter == 'pending',
                      onSelected: (_) => setState(() => _filter = 'pending'),
                    ),
                    const SizedBox(width: 6),
                    FilterChip(
                      label: Text('تعارض ($conflictCount)'),
                      selected: _filter == 'conflict',
                      selectedColor: Colors.red.withValues(alpha: 0.2),
                      onSelected: (_) => setState(() => _filter = 'conflict'),
                    ),
                    const SizedBox(width: 6),
                    FilterChip(
                      label: const Text('مكتمل'),
                      selected: _filter == 'acknowledged',
                      onSelected: (_) => setState(() => _filter = 'acknowledged'),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 8),

              // Operations List
              Expanded(
                child: _isLoading
                    ? const Center(child: CircularProgressIndicator())
                    : _filteredOperations.isEmpty
                        ? Center(
                            child: Text(
                              'لا توجد عمليات في هذا التصنيف',
                              style: TextStyle(color: isDark ? Colors.grey[400] : Colors.grey[600]),
                            ),
                          )
                        : ListView.separated(
                            itemCount: _filteredOperations.length,
                            separatorBuilder: (_, __) => const SizedBox(height: 8),
                            itemBuilder: (context, index) {
                              final op = _filteredOperations[index];
                              return _buildOperationCard(op, isDark);
                            },
                          ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildOperationCard(DurableOperation op, bool isDark) {
    Color statusColor;
    String statusLabel;
    IconData statusIcon;

    switch (op.status) {
      case DurableOperationStatus.acknowledged:
        statusColor = Colors.green;
        statusLabel = 'مؤكد (تم)';
        statusIcon = Icons.check_circle_outline;
        break;
      case DurableOperationStatus.conflict:
        statusColor = Colors.orange[800]!;
        statusLabel = 'تعارض (409)';
        statusIcon = Icons.warning_amber_rounded;
        break;
      case DurableOperationStatus.rejected:
        statusColor = Colors.red;
        statusLabel = 'مرفوض';
        statusIcon = Icons.cancel_outlined;
        break;
      case DurableOperationStatus.sending:
        statusColor = Colors.blue;
        statusLabel = 'جاري الإرسال';
        statusIcon = Icons.hourglass_top;
        break;
      case DurableOperationStatus.pending:
        statusColor = Colors.amber[800]!;
        statusLabel = 'قيد الانتظار';
        statusIcon = Icons.schedule;
        break;
    }

    final isActionable = op.status == DurableOperationStatus.conflict || op.status == DurableOperationStatus.rejected;

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: isDark ? AppColors.surfaceDark : Colors.grey.withValues(alpha: 0.05),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: op.status == DurableOperationStatus.conflict
              ? Colors.orange.withValues(alpha: 0.5)
              : Colors.grey.withValues(alpha: 0.2),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  Icon(statusIcon, size: 16, color: statusColor),
                  const SizedBox(width: 6),
                  Text(
                    _formatOpType(op.operationType),
                    style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
                  ),
                ],
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: statusColor.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  statusLabel,
                  style: TextStyle(color: statusColor, fontSize: 11, fontWeight: FontWeight.bold),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            'UUID: ${op.operationUuid.substring(0, (op.operationUuid.length > 20 ? 20 : op.operationUuid.length))}...',
            style: const TextStyle(fontFamily: 'monospace', fontSize: 10, color: Colors.grey),
          ),
          if (op.errorMessage != null && op.errorMessage!.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              'السبب: ${op.errorMessage}',
              style: TextStyle(
                fontSize: 11,
                color: op.status == DurableOperationStatus.conflict ? Colors.red[700] : Colors.grey[700],
              ),
            ),
          ],
          if (isActionable) ...[
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton.icon(
                  icon: const Icon(Icons.delete_outline, size: 14, color: Colors.red),
                  label: const Text('حذف', style: TextStyle(fontSize: 11, color: Colors.red)),
                  onPressed: () => _discardOperation(op.operationUuid),
                ),
                const SizedBox(width: 8),
                ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                    minimumSize: Size.zero,
                  ),
                  icon: const Icon(Icons.refresh, size: 14),
                  label: const Text('إعادة المحاولة', style: TextStyle(fontSize: 11)),
                  onPressed: () => _retryOperation(op.operationUuid),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  String _formatOpType(String type) {
    switch (type) {
      case 'pos_sale':
      case 'sale':
        return 'عملية بيع POS';
      case 'stock_adjustment':
      case 'inventory_movement':
        return 'تسوية مخزنية';
      case 'create_product':
        return 'إضافة منتج جديد';
      case 'stocktake_count':
        return 'جرد مخزني';
      default:
        return type;
    }
  }
}
