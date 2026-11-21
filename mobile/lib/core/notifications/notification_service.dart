import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

enum NotificationType {
  newMessage,
  newOrder,
  syncAlert,
  systemInfo,
}

class StoreAlert {
  final String id;
  final String title;
  final String body;
  final NotificationType type;
  final DateTime timestamp;
  final bool isRead;

  const StoreAlert({
    required this.id,
    required this.title,
    required this.body,
    required this.type,
    required this.timestamp,
    this.isRead = false,
  });

  StoreAlert copyWith({bool? isRead}) {
    return StoreAlert(
      id: id,
      title: title,
      body: body,
      type: type,
      timestamp: timestamp,
      isRead: isRead ?? this.isRead,
    );
  }
}

class NotificationService extends ChangeNotifier {
  static const String _prefKeySoundEnabled = 'notif_sound_enabled';
  static const String _prefKeyVibrationEnabled = 'notif_vibration_enabled';

  bool _soundEnabled = true;
  bool _vibrationEnabled = true;
  final List<StoreAlert> _alerts = [];

  bool get soundEnabled => _soundEnabled;
  bool get vibrationEnabled => _vibrationEnabled;
  List<StoreAlert> get alerts => List.unmodifiable(_alerts);
  int get unreadCount => _alerts.where((a) => !a.isRead).length;

  NotificationService() {
    _loadPreferences();
  }

  Future<void> _loadPreferences() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      _soundEnabled = prefs.getBool(_prefKeySoundEnabled) ?? true;
      _vibrationEnabled = prefs.getBool(_prefKeyVibrationEnabled) ?? true;
      notifyListeners();
    } catch (_) {}
  }

  Future<void> setSoundEnabled(bool enabled) async {
    _soundEnabled = enabled;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_prefKeySoundEnabled, enabled);
  }

  Future<void> setVibrationEnabled(bool enabled) async {
    _vibrationEnabled = enabled;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_prefKeyVibrationEnabled, enabled);
  }

  /// Trigger alert for a new incoming message or order
  void showAlert({
    required String title,
    required String body,
    required NotificationType type,
  }) {
    final alert = StoreAlert(
      id: DateTime.now().millisecondsSinceEpoch.toString(),
      title: title,
      body: body,
      type: type,
      timestamp: DateTime.now(),
    );

    _alerts.insert(0, alert);
    if (_alerts.length > 50) {
      _alerts.removeLast();
    }

    if (_vibrationEnabled) {
      HapticFeedback.mediumImpact();
    }

    notifyListeners();
  }

  void markAsRead(String id) {
    final index = _alerts.indexWhere((a) => a.id == id);
    if (index >= 0) {
      _alerts[index] = _alerts[index].copyWith(isRead: true);
      notifyListeners();
    }
  }

  void markAllAsRead() {
    for (int i = 0; i < _alerts.length; i++) {
      _alerts[i] = _alerts[i].copyWith(isRead: true);
    }
    notifyListeners();
  }
}
