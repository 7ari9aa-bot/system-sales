import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Secure credential store adhering to the Fihrist Master Plan.
/// Separates sensitive tokens/credentials (stored in Android Keystore / iOS Keychain)
/// from non-sensitive preferences (stored in SharedPreferences).
class SecureTokenStore {
  final FlutterSecureStorage _secureStorage;

  static const String _secKeyAccessToken = 'fihrist_sec_access_token';
  static const String _secKeyRefreshToken = 'fihrist_sec_refresh_token';
  static const String _secKeyTenantId = 'fihrist_sec_tenant_id';
  static const String _secKeyUserId = 'fihrist_sec_user_id';
  static const String _secKeyPinCode = 'fihrist_sec_pin_code';

  static const String _prefKeyBaseUrl = 'fihrist_pref_api_base_url';
  static const String _prefKeyTenantSubdomain = 'fihrist_pref_tenant_subdomain';
  static const String _prefKeyUserEmail = 'fihrist_pref_user_email';
  static const String _prefKeyUserName = 'fihrist_pref_user_name';
  static const String _prefKeyDeviceId = 'fihrist_pref_device_id';
  static const String _prefKeyRegisterId = 'fihrist_pref_register_id';

  SecureTokenStore({FlutterSecureStorage? secureStorage})
      : _secureStorage = secureStorage ??
            const FlutterSecureStorage(
              iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock),
            );

  Future<void> saveAuth({
    required String accessToken,
    required String refreshToken,
    required String tenantId,
    required String tenantSubdomain,
    String? userId,
    String? userEmail,
    String? userName,
  }) async {
    // 1. Sensitive credentials into secure hardware-backed storage
    await _safeWrite(_secKeyAccessToken, accessToken);
    await _safeWrite(_secKeyRefreshToken, refreshToken);
    await _safeWrite(_secKeyTenantId, tenantId);
    if (userId != null) {
      await _safeWrite(_secKeyUserId, userId);
    }

    // 2. Non-sensitive profile data into SharedPreferences
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefKeyTenantSubdomain, tenantSubdomain);
    if (userEmail != null) await prefs.setString(_prefKeyUserEmail, userEmail);
    if (userName != null) await prefs.setString(_prefKeyUserName, userName);
  }

  Future<String?> getAccessToken() => _safeRead(_secKeyAccessToken);
  Future<String?> getRefreshToken() => _safeRead(_secKeyRefreshToken);
  Future<String?> getTenantId() => _safeRead(_secKeyTenantId);
  Future<String?> getUserId() => _safeRead(_secKeyUserId);

  Future<void> saveAccessToken(String token) => _safeWrite(_secKeyAccessToken, token);
  Future<void> saveRefreshToken(String token) => _safeWrite(_secKeyRefreshToken, token);

  Future<String?> _safeRead(String key) async {
    try {
      return await _secureStorage.read(key: key);
    } catch (e) {
      // Hardware secure keystore error - never read sensitive keys from insecure storage
      return null;
    }
  }

  Future<void> _safeWrite(String key, String value) async {
    try {
      await _secureStorage.write(key: key, value: value);
    } catch (e) {
      throw Exception('فشل التخزين في وحدة التخزين المشفرة للجهاز (Keystore/Keychain): $e');
    }
  }

  Future<void> _safeDelete(String key) async {
    try {
      await _secureStorage.delete(key: key);
    } catch (_) {}
  }

  Future<String?> getTenantSubdomain() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_prefKeyTenantSubdomain);
  }

  Future<String?> getUserEmail() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_prefKeyUserEmail);
  }

  Future<String?> getUserName() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_prefKeyUserName);
  }

  Future<String?> getBaseUrl() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_prefKeyBaseUrl);
  }

  Future<void> setBaseUrl(String url) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefKeyBaseUrl, url);
  }

  Future<String> getOrCreateDeviceId() async {
    final prefs = await SharedPreferences.getInstance();
    String? deviceId = prefs.getString(_prefKeyDeviceId);
    if (deviceId == null || deviceId.isEmpty) {
      deviceId = 'dev_${DateTime.now().millisecondsSinceEpoch}_${(DateTime.now().microsecond % 1000).toString().padLeft(3, '0')}';
      await prefs.setString(_prefKeyDeviceId, deviceId);
    }
    return deviceId;
  }

  Future<String?> getRegisterId() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_prefKeyRegisterId);
  }

  Future<void> setRegisterId(String registerId) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefKeyRegisterId, registerId);
  }

  Future<void> savePin(String pin) => _safeWrite(_secKeyPinCode, pin);
  Future<String?> getPin() => _safeRead(_secKeyPinCode);

  /// Clears only authentication tokens on logout.
  /// Per the Master Plan: Pending offline queue operations are NEVER deleted on logout!
  Future<void> clearSession() async {
    await _safeDelete(_secKeyAccessToken);
    await _safeDelete(_secKeyRefreshToken);
    await _safeDelete(_secKeyPinCode);
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_prefKeyUserEmail);
    await prefs.remove(_prefKeyUserName);
  }

  Future<bool> isAuthenticated() async {
    final token = await getAccessToken();
    return token != null && token.isNotEmpty;
  }
}
