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
    final cleanSubdomain = tenantSubdomain.trim().toLowerCase();

    final response = await _apiClient.post(
      ApiEndpoints.login,
      body: {
        'subdomain': cleanSubdomain,
        'email': email.trim(),
        'password': password,
      },
      includeAuth: false,
      extraHeaders: {
        'X-Tenant-Subdomain': cleanSubdomain,
      },
    );

    if (response is Map<String, dynamic>) {
      final accessToken = response['access_token']?.toString() ??
          response['token']?.toString();
      if (accessToken == null || accessToken.trim().isEmpty) {
        throw ApiException(
          statusCode: 401,
          message: 'لم يتم استلام رمز دخول صالح من الخادم',
        );
      }

      final refreshToken = response['refresh_token']?.toString() ?? '';
      final tenantId = response['tenant_id']?.toString() ?? cleanSubdomain;
      final userData = response['user'] as Map<String, dynamic>? ?? response;
      final userId = userData['id']?.toString() ?? response['user_id']?.toString();

      await _tokenStore.saveAuth(
        accessToken: accessToken,
        refreshToken: refreshToken,
        tenantId: tenantId,
        tenantSubdomain: cleanSubdomain,
        userId: userId,
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
      // Never synthesize fake credentials when backend verification fails
      return null;
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
