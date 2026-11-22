import '../secure_storage/secure_token_store.dart';

/// Single authoritative token store facade that delegates directly
/// to SecureTokenStore (hardware Keystore/Keychain).
class AuthTokenStore {
  final SecureTokenStore _secureStore;

  AuthTokenStore({SecureTokenStore? secureStore})
      : _secureStore = secureStore ?? SecureTokenStore();

  Future<void> saveAuth({
    required String accessToken,
    required String refreshToken,
    required String tenantId,
    required String tenantSubdomain,
    String? userId,
    String? userEmail,
    String? userName,
  }) {
    return _secureStore.saveAuth(
      accessToken: accessToken,
      refreshToken: refreshToken,
      tenantId: tenantId,
      tenantSubdomain: tenantSubdomain,
      userId: userId,
      userEmail: userEmail,
      userName: userName,
    );
  }

  Future<String?> getAccessToken() => _secureStore.getAccessToken();
  Future<String?> getRefreshToken() => _secureStore.getRefreshToken();
  Future<void> saveAccessToken(String token) => _secureStore.saveAccessToken(token);
  Future<void> saveRefreshToken(String token) => _secureStore.saveRefreshToken(token);
  Future<String?> getTenantId() => _secureStore.getTenantId();
  Future<String?> getUserId() => _secureStore.getUserId();
  Future<String?> getTenantSubdomain() => _secureStore.getTenantSubdomain();
  Future<String?> getUserEmail() => _secureStore.getUserEmail();
  Future<String?> getUserName() => _secureStore.getUserName();
  Future<String?> getBaseUrl() => _secureStore.getBaseUrl();
  Future<void> setBaseUrl(String url) => _secureStore.setBaseUrl(url);
  Future<void> savePin(String pin) => _secureStore.savePin(pin);
  Future<String?> getPin() => _secureStore.getPin();
  Future<void> clear() => _secureStore.clearSession();
  Future<bool> isAuthenticated() => _secureStore.isAuthenticated();
}
