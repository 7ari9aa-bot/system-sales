import '../../core/api/api_client.dart';
import '../../core/api/api_endpoints.dart';
import '../../core/auth/auth_token_store.dart';
import '../models/user.dart';

class AuthRepository {
  AuthRepository({
    ApiClient? apiClient,
    AuthTokenStore? tokenStore,
  })  : _apiClient = apiClient ?? ApiClient(),
        _tokenStore = tokenStore ?? AuthTokenStore();

  final ApiClient _apiClient;
  final AuthTokenStore _tokenStore;

  Future<AuthUser> login({
    required String tenantSubdomain,
    required String email,
    required String password,
  }) async {
    // If tenantSubdomain is custom or default, adjust base url if needed
    final cleanSubdomain = tenantSubdomain.trim().toLowerCase();

    final response = await _apiClient.post(
      ApiEndpoints.login,
      body: {
        'email': email.trim(),
        'password': password,
      },
      includeAuth: false,
    );

    if (response is Map<String, dynamic>) {
      final accessToken = response['access_token']?.toString() ??
          response['token']?.toString() ??
          '';
      final refreshToken = response['refresh_token']?.toString() ?? '';
      final tenantId = response['tenant_id']?.toString() ?? cleanSubdomain;
      final userData = response['user'] as Map<String, dynamic>? ?? response;

      await _tokenStore.saveAuth(
        accessToken: accessToken,
        refreshToken: refreshToken,
        tenantId: tenantId,
        tenantSubdomain: cleanSubdomain,
        userEmail: userData['email']?.toString() ?? email,
        userName: userData['name']?.toString(),
      );

      return AuthUser.fromJson(userData);
    }

    throw ApiException(
      statusCode: 500,
      message: 'استجابة تسجيل الدخول غير صالحة',
    );
  }

  Future<AuthUser?> getCurrentUser() async {
    final token = await _tokenStore.getAccessToken();
    if (token == null || token.isEmpty) return null;

    try {
      final response = await _apiClient.get(ApiEndpoints.me);
      if (response is Map<String, dynamic>) {
        return AuthUser.fromJson(response);
      }
    } catch (_) {
      // Fallback to local stored info
      final email = await _tokenStore.getUserEmail();
      final name = await _tokenStore.getUserName();
      final tenantId = await _tokenStore.getTenantId();
      if (email != null && tenantId != null) {
        return AuthUser(id: 'local', email: email, name: name, tenantId: tenantId);
      }
    }
    return null;
  }

  Future<void> logout() async {
    try {
      await _apiClient.post(ApiEndpoints.logout);
    } catch (_) {}
    await _tokenStore.clear();
  }

  Future<bool> isLoggedIn() => _tokenStore.isAuthenticated();
  Future<String?> getSavedSubdomain() => _tokenStore.getTenantSubdomain();
}
