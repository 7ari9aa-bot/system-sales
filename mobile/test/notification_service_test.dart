import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:fihrist_mobile/core/notifications/notification_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('NotificationService', () {
    setUp(() {
      SharedPreferences.setMockInitialValues({});
    });

    test('dispatches alerts and increments unread count', () {
      final notif = NotificationService();
      expect(notif.unreadCount, 0);
      expect(notif.alerts, isEmpty);

      notif.showAlert(
        title: 'رسالة جديدة',
        body: 'العميل يسأل عن توفر القهوة المختصة',
        type: NotificationType.newMessage,
      );

      expect(notif.unreadCount, 1);
      expect(notif.alerts.length, 1);
      expect(notif.alerts.first.title, 'رسالة جديدة');

      notif.showAlert(
        title: 'طلب جديد #102',
        body: 'تم استلام طلب جديد بقيمة 150 ر.س',
        type: NotificationType.newOrder,
      );

      expect(notif.unreadCount, 2);
      expect(notif.alerts.length, 2);

      // Mark first as read
      notif.markAsRead(notif.alerts.first.id);
      expect(notif.unreadCount, 1);

      // Mark all as read
      notif.markAllAsRead();
      expect(notif.unreadCount, 0);
    });

    test('toggles sound and vibration preferences', () async {
      final notif = NotificationService();
      expect(notif.soundEnabled, isTrue);
      expect(notif.vibrationEnabled, isTrue);

      await notif.setSoundEnabled(false);
      expect(notif.soundEnabled, isFalse);

      await notif.setVibrationEnabled(false);
      expect(notif.vibrationEnabled, isFalse);
    });
  });
}
