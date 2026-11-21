import 'package:shared_preferences/shared_preferences.dart';

class AuthTokenStore {
  static const String _keyAccessToken = 'auth_access_token';
  static const String _keyRefreshToken = 'auth_refresh_token';
  static const String _keyTenantId = 'auth_tenant_id';
  static const String _keyTenantSubdomain = 'auth_tenant_subdomain';
  static const String _keyUserEmail = 'auth_user_email';
  static const String _keyUserName = 'auth_user_name';
  static const String _keyBaseUrl = 'api_base_url';

  Future<void> saveAuth({
    required String accessToken,
    required String refreshToken,
    required String tenantId,
    required String tenantSubdomain,
    String? userEmail,
    String? userName,
  }) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyAccessToken, accessToken);
    await prefs.setString(_keyRefreshToken, refreshToken);
    await prefs.setString(_keyTenantId, tenantId);
    await prefs.setString(_keyTenantSubdomain, tenantSubdomain);
    if (userEmail != null) await prefs.setString(_keyUserEmail, userEmail);
    if (userName != null) await prefs.setString(_keyUserName, userName);
  }

  Future<String?> getAccessToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_keyAccessToken);
  }

  Future<String?> getRefreshToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_keyRefreshToken);
  }

  Future<String?> getTenantId() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_keyTenantId);
  }

  Future<String?> getTenantSubdomain() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_keyTenantSubdomain);
  }

  Future<String?> getUserEmail() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_keyUserEmail);
  }

  Future<String?> getUserName() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_keyUserName);
  }

  Future<String?> getBaseUrl() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_keyBaseUrl);
  }

  Future<void> setBaseUrl(String url) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyBaseUrl, url);
  }

  Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_keyAccessToken);
    await prefs.remove(_keyRefreshToken);
    await prefs.remove(_keyTenantId);
    await prefs.remove(_keyUserEmail);
    await prefs.remove(_keyUserName);
  }

  Future<bool> isAuthenticated() async {
    final token = await getAccessToken();
    return token != null && token.isNotEmpty;
  }
}
