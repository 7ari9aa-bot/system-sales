import 'package:flutter/material.dart';
import '../data/models/conversation.dart';
import '../data/repositories/chat_repository.dart';

class ChatViewModel extends ChangeNotifier {
  ChatViewModel({ChatRepository? chatRepository})
      : _chatRepository = chatRepository ?? ChatRepository() {
    loadThreads();
  }

  final ChatRepository _chatRepository;

  List<ConversationThread> _threads = [];
  ChannelType? _selectedChannel;
  ConversationThread? _activeThread;
  List<ChatMessage> _activeMessages = [];
  bool _isLoading = false;
  bool _isSending = false;

  List<ConversationThread> get threads => _threads;
  ChannelType? get selectedChannel => _selectedChannel;
  ConversationThread? get activeThread => _activeThread;
  List<ChatMessage> get activeMessages => _activeMessages;
  bool get isLoading => _isLoading;
  bool get isSending => _isSending;

  Future<void> loadThreads() async {
    _isLoading = true;
    notifyListeners();

    try {
      _threads = await _chatRepository.getThreads(channel: _selectedChannel);
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  void filterByChannel(ChannelType? channel) {
    if (_selectedChannel == channel) return;
    _selectedChannel = channel;
    loadThreads();
  }

  Future<void> selectThread(ConversationThread thread) async {
    _activeThread = thread;
    _activeMessages = [];
    _isLoading = true;
    notifyListeners();

    try {
      _activeMessages = await _chatRepository.getMessages(thread.id);
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> toggleAiActive() async {
    if (_activeThread == null) return;
    final updated = _activeThread!.copyWith(isAiActive: !_activeThread!.isAiActive);
    _activeThread = updated;
    final idx = _threads.indexWhere((t) => t.id == updated.id);
    if (idx >= 0) {
      _threads[idx] = updated;
    }
    notifyListeners();
  }

  Future<void> sendMessage(String text) async {
    if (_activeThread == null || text.trim().isEmpty) return;

    final trimmed = text.trim();
    _isSending = true;
    notifyListeners();

    try {
      final newMsg = await _chatRepository.sendMessage(
        conversationId: _activeThread!.id,
        text: trimmed,
      );
      _activeMessages.add(newMsg);
    } finally {
      _isSending = false;
      notifyListeners();
    }
  }
}
