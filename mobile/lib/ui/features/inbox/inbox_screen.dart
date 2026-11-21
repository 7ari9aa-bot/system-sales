import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../core/constants/app_colors.dart';
import '../../../data/models/conversation.dart';
import '../../../l10n/generated/app_localizations.dart';
import '../../../providers/chat_view_model.dart';
import 'conversation_screen.dart';

class InboxScreen extends StatelessWidget {
  const InboxScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final chatVm = context.watch<ChatViewModel>();
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.inboxTitle),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => chatVm.loadThreads(),
            tooltip: l10n.retry,
          ),
        ],
      ),
      body: Column(
        children: [
          // Channel Filter Chips
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Row(
              children: [
                _buildChannelFilterChip(
                  context,
                  label: 'الكل',
                  isSelected: chatVm.selectedChannel == null,
                  onSelected: () => chatVm.filterByChannel(null),
                ),
                const SizedBox(width: 8),
                _buildChannelFilterChip(
                  context,
                  label: l10n.channelWhatsApp,
                  icon: Icons.chat,
                  iconColor: AppColors.whatsapp,
                  isSelected: chatVm.selectedChannel == ChannelType.whatsapp,
                  onSelected: () => chatVm.filterByChannel(ChannelType.whatsapp),
                ),
                const SizedBox(width: 8),
                _buildChannelFilterChip(
                  context,
                  label: l10n.channelInstagram,
                  icon: Icons.camera_alt,
                  iconColor: AppColors.instagram,
                  isSelected: chatVm.selectedChannel == ChannelType.instagram,
                  onSelected: () => chatVm.filterByChannel(ChannelType.instagram),
                ),
                const SizedBox(width: 8),
                _buildChannelFilterChip(
                  context,
                  label: l10n.channelTelegram,
                  icon: Icons.send,
                  iconColor: AppColors.telegram,
                  isSelected: chatVm.selectedChannel == ChannelType.telegram,
                  onSelected: () => chatVm.filterByChannel(ChannelType.telegram),
                ),
              ],
            ),
          ),
          const Divider(height: 1),

          // Conversation List
          Expanded(
            child: chatVm.isLoading && chatVm.threads.isEmpty
                ? const Center(child: CircularProgressIndicator())
                : chatVm.threads.isEmpty
                    ? Center(
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(
                              Icons.forum_outlined,
                              size: 48,
                              color: isDark ? Colors.grey[600] : Colors.grey[400],
                            ),
                            const SizedBox(height: 12),
                            const Text('لا توجد محادثات في هذه القناة'),
                          ],
                        ),
                      )
                    : ListView.separated(
                        itemCount: chatVm.threads.length,
                        separatorBuilder: (_, __) => const Divider(height: 1),
                        itemBuilder: (context, index) {
                          final thread = chatVm.threads[index];
                          return _buildThreadTile(context, thread, isDark);
                        },
                      ),
          ),
        ],
      ),
    );
  }

  Widget _buildChannelFilterChip(
    BuildContext context, {
    required String label,
    IconData? icon,
    Color? iconColor,
    required bool isSelected,
    required VoidCallback onSelected,
  }) {
    return ChoiceChip(
      avatar: icon != null ? Icon(icon, size: 16, color: iconColor) : null,
      label: Text(label),
      selected: isSelected,
      onSelected: (_) => onSelected(),
    );
  }

  Widget _buildThreadTile(
    BuildContext context,
    ConversationThread thread,
    bool isDark,
  ) {
    final l10n = AppLocalizations.of(context)!;
    final chatVm = context.read<ChatViewModel>();

    return ListTile(
      onTap: () {
        chatVm.selectThread(thread);
        Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => ConversationScreen(thread: thread),
          ),
        );
      },
      leading: Stack(
        children: [
          CircleAvatar(
            backgroundColor: AppColors.primary.withValues(alpha: 0.12),
            child: Text(
              thread.customerName.isNotEmpty
                  ? thread.customerName.characters.first
                  : 'C',
              style: const TextStyle(
                color: AppColors.primary,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
          Positioned(
            right: 0,
            bottom: 0,
            child: Container(
              padding: const EdgeInsets.all(2),
              decoration: const BoxDecoration(
                color: Colors.white,
                shape: BoxShape.circle,
              ),
              child: Icon(
                _getChannelIcon(thread.channel),
                size: 14,
                color: _getChannelColor(thread.channel),
              ),
            ),
          ),
        ],
      ),
      title: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Expanded(
            child: Text(
              thread.customerName,
              style: const TextStyle(fontWeight: FontWeight.bold),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          Text(
            _formatTime(thread.lastMessageAt),
            style: TextStyle(
              fontSize: 11,
              color: isDark ? Colors.grey[400] : Colors.grey[600],
            ),
          ),
        ],
      ),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 4),
          Row(
            children: [
              Expanded(
                child: Text(
                  thread.lastMessage,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 13,
                    color: isDark
                        ? AppColors.textSecondaryDark
                        : AppColors.textSecondaryLight,
                  ),
                ),
              ),
              if (thread.isAiActive) ...[
                const SizedBox(width: 6),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: AppColors.secondary.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(
                        Icons.auto_awesome,
                        size: 10,
                        color: AppColors.secondary,
                      ),
                      const SizedBox(width: 2),
                      Text(
                        l10n.aiAgentActive.split(' ').first,
                        style: const TextStyle(
                          fontSize: 10,
                          fontWeight: FontWeight.bold,
                          color: AppColors.secondary,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
              if (thread.unreadCount > 0) ...[
                const SizedBox(width: 6),
                CircleAvatar(
                  radius: 9,
                  backgroundColor: AppColors.primary,
                  child: Text(
                    '${thread.unreadCount}',
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 10,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ],
            ],
          ),
        ],
      ),
    );
  }

  IconData _getChannelIcon(ChannelType channel) {
    switch (channel) {
      case ChannelType.whatsapp:
        return Icons.chat;
      case ChannelType.instagram:
        return Icons.camera_alt;
      case ChannelType.telegram:
        return Icons.send;
      default:
        return Icons.message;
    }
  }

  Color _getChannelColor(ChannelType channel) {
    switch (channel) {
      case ChannelType.whatsapp:
        return AppColors.whatsapp;
      case ChannelType.instagram:
        return AppColors.instagram;
      case ChannelType.telegram:
        return AppColors.telegram;
      default:
        return AppColors.primary;
    }
  }

  String _formatTime(DateTime time) {
    final now = DateTime.now();
    final diff = now.difference(time);
    if (diff.inMinutes < 60) {
      return 'منذ ${diff.inMinutes} د';
    } else if (diff.inHours < 24) {
      return 'منذ ${diff.inHours} س';
    }
    return '${time.day}/${time.month}';
  }
}
