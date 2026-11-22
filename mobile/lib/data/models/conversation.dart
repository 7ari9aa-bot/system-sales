enum ChannelType {
  whatsapp,
  instagram,
  telegram,
  messenger,
  web,
  other;

  static ChannelType fromString(String? value) {
    switch (value?.toLowerCase()) {
      case 'whatsapp':
        return ChannelType.whatsapp;
      case 'instagram':
        return ChannelType.instagram;
      case 'telegram':
        return ChannelType.telegram;
      case 'messenger':
      case 'facebook':
        return ChannelType.messenger;
      case 'web':
        return ChannelType.web;
      default:
        return ChannelType.other;
    }
  }
}

class ConversationThread {
  final String id;
  final String customerName;
  final String? customerPhone;
  final ChannelType channel;
  final String lastMessage;
  final DateTime lastMessageAt;
  final int unreadCount;
  final bool isAiActive;
  final String? avatarUrl;

  const ConversationThread({
    required this.id,
    required this.customerName,
    this.customerPhone,
    required this.channel,
    required this.lastMessage,
    required this.lastMessageAt,
    this.unreadCount = 0,
    this.isAiActive = true,
    this.avatarUrl,
  });

  factory ConversationThread.fromJson(Map<String, dynamic> json) {
    return ConversationThread(
      id: json['id']?.toString() ?? '',
      customerName: json['customer_name']?.toString() ??
          json['customer']?['name']?.toString() ??
          'عميل',
      customerPhone: json['customer_phone']?.toString() ??
          json['customer']?['phone']?.toString(),
      channel: ChannelType.fromString(json['channel']?.toString()),
      lastMessage: json['last_message']?.toString() ?? '',
      lastMessageAt: json['last_message_at'] != null
          ? DateTime.tryParse(json['last_message_at'].toString()) ?? DateTime.now()
          : DateTime.now(),
      unreadCount: (json['unread_count'] as num?)?.toInt() ?? 0,
      isAiActive: json['is_ai_active'] ?? json['ai_active'] ?? true,
      avatarUrl: json['avatar_url']?.toString(),
    );
  }

  ConversationThread copyWith({
    String? id,
    String? customerName,
    String? customerPhone,
    ChannelType? channel,
    String? lastMessage,
    DateTime? lastMessageAt,
    int? unreadCount,
    bool? isAiActive,
    String? avatarUrl,
  }) {
    return ConversationThread(
      id: id ?? this.id,
      customerName: customerName ?? this.customerName,
      customerPhone: customerPhone ?? this.customerPhone,
      channel: channel ?? this.channel,
      lastMessage: lastMessage ?? this.lastMessage,
      lastMessageAt: lastMessageAt ?? this.lastMessageAt,
      unreadCount: unreadCount ?? this.unreadCount,
      isAiActive: isAiActive ?? this.isAiActive,
      avatarUrl: avatarUrl ?? this.avatarUrl,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'customer_name': customerName,
        'customer_phone': customerPhone,
        'channel': channel.name,
        'last_message': lastMessage,
        'last_message_at': lastMessageAt.toIso8601String(),
        'unread_count': unreadCount,
        'is_ai_active': isAiActive,
        'avatar_url': avatarUrl,
      };
}

class ChatMessage {
  final String id;
  final String conversationId;
  final String senderType; // "customer", "agent", "ai"
  final String text;
  final String? mediaUrl;
  final DateTime timestamp;
  final bool isOutgoing;

  const ChatMessage({
    required this.id,
    required this.conversationId,
    required this.senderType,
    required this.text,
    this.mediaUrl,
    required this.timestamp,
    required this.isOutgoing,
  });

  factory ChatMessage.fromJson(Map<String, dynamic> json) {
    final sender = json['sender_type']?.toString() ?? json['role']?.toString() ?? 'agent';
    final direction = json['direction']?.toString();
    return ChatMessage(
      id: json['id']?.toString() ?? '',
      conversationId: json['conversation_id']?.toString() ?? '',
      senderType: sender,
      text: json['body']?.toString() ?? json['text']?.toString() ?? json['content']?.toString() ?? '',
      mediaUrl: json['media_url']?.toString(),
      timestamp: json['created_at'] != null
          ? DateTime.tryParse(json['created_at'].toString()) ?? DateTime.now()
          : (json['timestamp'] != null
              ? DateTime.tryParse(json['timestamp'].toString()) ?? DateTime.now()
              : DateTime.now()),
      isOutgoing: direction == 'outbound' || sender == 'agent' || sender == 'ai' || sender == 'assistant',
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'conversation_id': conversationId,
        'sender_type': senderType,
        'text': text,
        'media_url': mediaUrl,
        'timestamp': timestamp.toIso8601String(),
        'is_outgoing': isOutgoing,
      };
}
