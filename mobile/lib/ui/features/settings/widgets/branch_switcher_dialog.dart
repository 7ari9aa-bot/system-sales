import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../../core/constants/app_colors.dart';
import '../../../../providers/auth_view_model.dart';

class BranchSwitcherDialog extends StatelessWidget {
  const BranchSwitcherDialog({super.key});

  @override
  Widget build(BuildContext context) {
    final authVm = context.watch<AuthViewModel>();
    final activeBranch = authVm.activeBranch;
    final branches = authVm.availableBranches;
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return AlertDialog(
      title: const Row(
        children: [
          Icon(Icons.store, color: AppColors.primary),
          SizedBox(width: 8),
          Text(
            'تبديل فرع التشغيل',
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
          ),
        ],
      ),
      content: SizedBox(
        width: double.maxFinite,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'اختر الفرع للعمل عليه في جلسة نقطة البيع الحالية:',
              style: TextStyle(fontSize: 13, color: Colors.grey),
            ),
            const SizedBox(height: 12),
            ...branches.map((branch) {
              final isSelected = branch.id == activeBranch.id;
              return Container(
                margin: const EdgeInsets.only(bottom: 8),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(
                    color: isSelected
                        ? AppColors.primary
                        : (isDark ? Colors.white12 : Colors.grey.shade300),
                    width: isSelected ? 2 : 1,
                  ),
                  color: isSelected
                      ? AppColors.primary.withValues(alpha: 0.08)
                      : Colors.transparent,
                ),
                child: ListTile(
                  dense: true,
                  leading: CircleAvatar(
                    radius: 16,
                    backgroundColor: isSelected
                        ? AppColors.primary
                        : Colors.grey.withValues(alpha: 0.2),
                    child: Icon(
                      branch.isMain ? Icons.home_work : Icons.location_on,
                      size: 16,
                      color: isSelected ? Colors.white : Colors.grey,
                    ),
                  ),
                  title: Text(
                    branch.name,
                    style: TextStyle(
                      fontWeight:
                          isSelected ? FontWeight.bold : FontWeight.normal,
                      fontSize: 14,
                    ),
                  ),
                  subtitle: Text(
                    '${branch.code} • ${branch.location}',
                    style: const TextStyle(fontSize: 11),
                  ),
                  trailing: isSelected
                      ? const Icon(Icons.check_circle,
                          color: AppColors.primary, size: 20)
                      : null,
                  onTap: () {
                    authVm.switchBranch(branch);
                    Navigator.pop(context);
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        content: Text('تم تبديل الفرع إلى: ${branch.name}'),
                        backgroundColor: AppColors.primary,
                        duration: const Duration(seconds: 2),
                      ),
                    );
                  },
                ),
              );
            }),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('إغلاق'),
        ),
      ],
    );
  }
}
