import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../core/constants/app_colors.dart';
import '../../../data/models/conversation.dart';
import '../../../l10n/generated/app_localizations.dart';
import '../../../providers/chat_view_model.dart';

class ConversationScreen extends StatefulWidget {
  final ConversationThread thread;

  const ConversationScreen({super.key, required this.thread});

  @override
  State<ConversationScreen> createState() => _ConversationScreenState();
}

class _ConversationScreenState extends State<ConversationScreen> {
  final _messageController = TextEditingController();
  final _scrollController = ScrollController();

  @override
  void dispose() {
    _messageController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _sendMessage() {
    final text = _messageController.text.trim();
    if (text.isEmpty) return;

    final chatVm = context.read<ChatViewModel>();
    chatVm.sendMessage(text);
    _messageController.clear();

    Future.delayed(const Duration(milliseconds: 100), () {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final chatVm = context.watch<ChatViewModel>();
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Scaffold(
      appBar: AppBar(
        titleSpacing: 0,
        title: Row(
          children: [
            CircleAvatar(
              radius: 18,
              backgroundColor: AppColors.primary.withValues(alpha: 0.15),
              child: Text(
                widget.thread.customerName.isNotEmpty
                    ? widget.thread.customerName.characters.first
                    : 'C',
                style: const TextStyle(
                  color: AppColors.primary,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    widget.thread.customerName,
                    style: const TextStyle(fontSize: 15, fontWeight: FontWeight.bold),
                    overflow: TextOverflow.ellipsis,
                  ),
                  if (widget.thread.customerPhone != null)
                    Text(
                      widget.thread.customerPhone!,
                      style: TextStyle(
                        fontSize: 11,
                        color: isDark ? Colors.grey[400] : Colors.grey[600],
                      ),
                    ),
                ],
              ),
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: Icon(
              chatVm.activeThread?.isAiActive ?? widget.thread.isAiActive
                  ? Icons.smart_toy
                  : Icons.smart_toy_outlined,
              color: (chatVm.activeThread?.isAiActive ?? widget.thread.isAiActive)
                  ? AppColors.secondary
                  : Colors.grey,
            ),
            tooltip: (chatVm.activeThread?.isAiActive ?? widget.thread.isAiActive)
                ? 'الرد الآلي مفعل (انقر للتعطيل وتدخل الموظف)'
                : 'الرد الآلي متوقف (انقر لإعادة تفعيل الذكاء الاصطناعي)',
            onPressed: () {
              chatVm.toggleAiActive();
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text(
                    chatVm.activeThread?.isAiActive == true
                        ? 'تم تفعيل الذكاء الاصطناعي للمحادثة'
                        : 'تم إيقاف الرد الآلي وتدخل الموظف يدوياً',
                  ),
                  duration: const Duration(seconds: 2),
                ),
              );
            },
          ),
          Container(
            margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 12),
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: (chatVm.activeThread?.isAiActive ?? widget.thread.isAiActive)
                  ? AppColors.secondary.withValues(alpha: 0.12)
                  : Colors.grey.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(
              children: [
                Icon(
                  Icons.auto_awesome,
                  size: 14,
                  color: (chatVm.activeThread?.isAiActive ?? widget.thread.isAiActive)
                      ? AppColors.secondary
                      : Colors.grey,
                ),
                const SizedBox(width: 4),
                Text(
                  (chatVm.activeThread?.isAiActive ?? widget.thread.isAiActive)
                      ? 'AI نشط'
                      : 'تدخل موظف',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                    color: (chatVm.activeThread?.isAiActive ?? widget.thread.isAiActive)
                        ? AppColors.secondary
                        : Colors.grey,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
      body: Column(
        children: [
          // Messages List
          Expanded(
            child: chatVm.isLoading && chatVm.activeMessages.isEmpty
                ? const Center(child: CircularProgressIndicator())
                : ListView.builder(
                    controller: _scrollController,
                    padding: const EdgeInsets.all(16),
                    itemCount: chatVm.activeMessages.length,
                    itemBuilder: (context, index) {
                      final msg = chatVm.activeMessages[index];
                      return _buildMessageBubble(context, msg, isDark);
                    },
                  ),
          ),

          // Quick Replies Row
          SizedBox(
            height: 38,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12),
              children: [
                _buildQuickReplyChip('أهلاً بك، كيف نقدر نساعدك؟'),
                const SizedBox(width: 8),
                _buildQuickReplyChip('طلبك قيد التجهيز والتوصيل'),
                const SizedBox(width: 8),
                _buildQuickReplyChip('تم استلام المبلغ بنجاح، شكراً لك'),
                const SizedBox(width: 8),
                _buildQuickReplyChip('المنتج متوفر بالمخزون ويمكنك الطلب'),
              ],
            ),
          ),
          const SizedBox(height: 4),

          // Message Input Bar
          Container(
            padding: EdgeInsets.only(
              left: 12,
              right: 12,
              top: 8,
              bottom: MediaQuery.of(context).viewInsets.bottom + 8,
            ),
            decoration: BoxDecoration(
              color: isDark ? AppColors.surfaceDark : Colors.white,
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.05),
                  blurRadius: 4,
                  offset: const Offset(0, -2),
                ),
              ],
            ),
            child: SafeArea(
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _messageController,
                      decoration: InputDecoration(
                        hintText: l10n.typeMessageHint,
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 16,
                          vertical: 10,
                        ),
                      ),
                      onSubmitted: (_) => _sendMessage(),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Container(
                    width: 48,
                    height: 48,
                    decoration: const BoxDecoration(
                      color: AppColors.primary,
                      shape: BoxShape.circle,
                    ),
                    child: IconButton(
                      icon: chatVm.isSending
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(
                                color: Colors.white,
                                strokeWidth: 2,
                              ),
                            )
                          : const Icon(Icons.send, color: Colors.white, size: 20),
                      onPressed: chatVm.isSending ? null : _sendMessage,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMessageBubble(
    BuildContext context,
    ChatMessage msg,
    bool isDark,
  ) {
    final isOutgoing = msg.isOutgoing;
    final isAi = msg.senderType == 'ai';

    return Align(
      alignment: isOutgoing ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.75,
        ),
        decoration: BoxDecoration(
          color: isOutgoing
              ? (isAi ? AppColors.secondary : AppColors.primary)
              : (isDark ? AppColors.cardDark : const Color(0xFFF1F5F9)),
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(16),
            topRight: const Radius.circular(16),
            bottomLeft: Radius.circular(isOutgoing ? 16 : 4),
            bottomRight: Radius.circular(isOutgoing ? 4 : 16),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (isAi)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.auto_awesome, size: 12, color: Colors.white70),
                    const SizedBox(width: 4),
                    Text(
                      'وكيل الذكاء الاصطناعي',
                      style: TextStyle(
                        fontSize: 10,
                        fontWeight: FontWeight.bold,
                        color: Colors.white.withValues(alpha: 0.85),
                      ),
                    ),
                  ],
                ),
              ),
            Text(
              msg.text,
              style: TextStyle(
                color: isOutgoing
                    ? Colors.white
                    : (isDark ? Colors.white : AppColors.textPrimaryLight),
                fontSize: 14,
              ),
            ),
            const SizedBox(height: 4),
            Align(
              alignment: Alignment.bottomRight,
              child: Text(
                '${msg.timestamp.hour.toString().padLeft(2, '0')}:${msg.timestamp.minute.toString().padLeft(2, '0')}',
                style: TextStyle(
                  fontSize: 10,
                  color: isOutgoing
                      ? Colors.white.withValues(alpha: 0.7)
                      : (isDark ? Colors.grey[400] : Colors.grey[600]),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildQuickReplyChip(String text) {
    return ActionChip(
      padding: EdgeInsets.zero,
      label: Text(text, style: const TextStyle(fontSize: 11)),
      onPressed: () {
        _messageController.text = text;
      },
    );
  }
}
