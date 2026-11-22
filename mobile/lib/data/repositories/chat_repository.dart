import '../../core/api/api_client.dart';
import '../../core/api/api_endpoints.dart';
import '../models/conversation.dart';

class ChatRepository {
  ChatRepository({ApiClient? apiClient})
      : _apiClient = apiClient ?? ApiClient();

  final ApiClient _apiClient;

  Future<List<ConversationThread>> getThreads({ChannelType? channel}) async {
    try {
      final query = <String, String>{};
      if (channel != null && channel != ChannelType.other) {
        query['channel'] = channel.name;
      }

      final response = await _apiClient.get(
        ApiEndpoints.inbox,
        queryParams: query.isNotEmpty ? query : null,
      );

      List<dynamic>? rawList;
      if (response is List) {
        rawList = response;
      } else if (response is Map<String, dynamic> && response['items'] is List) {
        rawList = response['items'] as List<dynamic>;
      }

      if (rawList != null) {
        return rawList
            .map((item) =>
                ConversationThread.fromJson(item as Map<String, dynamic>))
            .toList();
      }
    } catch (_) {}

    // Return mock threads when backend is unreachable or for fast offline preview
    return _mockThreads.where((t) {
      if (channel == null) return true;
      return t.channel == channel;
    }).toList();
  }

  Future<List<ChatMessage>> getMessages(String conversationId) async {
    try {
      final response = await _apiClient.get(
        ApiEndpoints.conversationMessages(conversationId),
      );

      List<dynamic>? rawList;
      if (response is List) {
        rawList = response;
      } else if (response is Map<String, dynamic> && response['items'] is List) {
        rawList = response['items'] as List<dynamic>;
      }

      if (rawList != null) {
        return rawList
            .map((item) => ChatMessage.fromJson(item as Map<String, dynamic>))
            .toList();
      }
    } catch (_) {}

    return _mockMessages[conversationId] ??
        [
          ChatMessage(
            id: 'm1',
            conversationId: conversationId,
            senderType: 'customer',
            text: 'السلام عليكم، هل متوفر التوصيل اليوم في الرياض؟',
            timestamp: DateTime.now().subtract(const Duration(minutes: 15)),
            isOutgoing: false,
          ),
          ChatMessage(
            id: 'm2',
            conversationId: conversationId,
            senderType: 'ai',
            text: 'أهلاً بك! نعم متاح التوصيل الفوري داخل الرياض خلال ساعتين.',
            timestamp: DateTime.now().subtract(const Duration(minutes: 14)),
            isOutgoing: true,
          ),
        ];
  }

  Future<ChatMessage> sendMessage({
    required String conversationId,
    required String text,
  }) async {
    // Backend SendMessageRequest requires 'body' field per OpenAPI contract
    final payload = {'body': text, 'sender_type': 'agent'};

    try {
      final response = await _apiClient.post(
        ApiEndpoints.conversationMessages(conversationId),
        body: payload,
      );

      if (response is Map<String, dynamic>) {
        return ChatMessage.fromJson(response);
      }
    } catch (_) {}

    return ChatMessage(
      id: 'msg_${DateTime.now().millisecondsSinceEpoch}',
      conversationId: conversationId,
      senderType: 'agent',
      text: text,
      timestamp: DateTime.now(),
      isOutgoing: true,
    );
  }

  static final List<ConversationThread> _mockThreads = [
    ConversationThread(
      id: 'c1',
      customerName: 'محمد الشهري',
      customerPhone: '+966501234567',
      channel: ChannelType.whatsapp,
      lastMessage: 'تمام، هطلب صندوقين تمر سكري ملكي',
      lastMessageAt: DateTime.now().subtract(const Duration(minutes: 5)),
      unreadCount: 2,
      isAiActive: true,
    ),
    ConversationThread(
      id: 'c2',
      customerName: 'سارة العتيبي',
      customerPhone: '+966559876543',
      channel: ChannelType.instagram,
      lastMessage: 'كم سعر كيلو الهيل الأمريكي؟',
      lastMessageAt: DateTime.now().subtract(const Duration(hours: 1)),
      unreadCount: 0,
      isAiActive: true,
    ),
    ConversationThread(
      id: 'c3',
      customerName: 'عبدالله الدوسري',
      customerPhone: '+966567788990',
      channel: ChannelType.telegram,
      lastMessage: 'تم تحويل المبلغ وهذا إشعار السداد',
      lastMessageAt: DateTime.now().subtract(const Duration(hours: 3)),
      unreadCount: 1,
      isAiActive: false,
    ),
  ];

  static final Map<String, List<ChatMessage>> _mockMessages = {
    'c1': [
      ChatMessage(
        id: 'c1_1',
        conversationId: 'c1',
        senderType: 'customer',
        text: 'مرحبا، هل عندكم عروض على التمور اليوم؟',
        timestamp: DateTime.now().subtract(const Duration(minutes: 20)),
        isOutgoing: false,
      ),
      ChatMessage(
        id: 'c1_2',
        conversationId: 'c1',
        senderType: 'ai',
        text: 'أهلاً وسهلاً بك في متجرنا! نعم لدينا عرض خاص على السكري الملكي 1كجم بسعر 65 ر.س.',
        timestamp: DateTime.now().subtract(const Duration(minutes: 18)),
        isOutgoing: true,
      ),
      ChatMessage(
        id: 'c1_3',
        conversationId: 'c1',
        senderType: 'customer',
        text: 'تمام، هطلب صندوقين تمر سكري ملكي',
        timestamp: DateTime.now().subtract(const Duration(minutes: 5)),
        isOutgoing: false,
      ),
    ],
  };
}
