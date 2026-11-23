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
    String tenantSubdomain = '',
    required String email,
    required String password,
  }) async {
    final cleanSubdomain = tenantSubdomain.trim().toLowerCase();

    final response = await _apiClient.post(
      ApiEndpoints.login,
      body: {
        'email': email.trim(),
        'password': password,
      },
      includeAuth: false,
      extraHeaders: {
        if (cleanSubdomain.isNotEmpty) 'X-Tenant-Subdomain': cleanSubdomain,
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

      // Save token so upcoming me request sends Bearer header
      await _tokenStore.saveAccessToken(accessToken);
      if (refreshToken.isNotEmpty) {
        await _tokenStore.saveRefreshToken(refreshToken);
      }

      // Fetch authentic user profile & tenant memberships from /auth/me
      Map<String, dynamic> meData = {};
      try {
        final meRes = await _apiClient.get(
          ApiEndpoints.me,
          extraHeaders: {
            'Authorization': 'Bearer $accessToken',
          },
        );
        if (meRes is Map<String, dynamic>) {
          meData = meRes;
        }
      } catch (_) {
        // If /auth/me unavailable, fallback to response payload
      }

      final rawTenants = (meData['tenants'] as List<dynamic>?) ?? [];
      Map<String, dynamic>? selectedTenantMap;

      if (rawTenants.isNotEmpty) {
        if (cleanSubdomain.isNotEmpty) {
          selectedTenantMap = rawTenants.cast<Map<String, dynamic>>().firstWhere(
                (t) =>
                    t['slug']?.toString().toLowerCase() == cleanSubdomain ||
                    t['name']?.toString().toLowerCase() == cleanSubdomain,
                orElse: () => rawTenants.first as Map<String, dynamic>,
              );
        } else {
          selectedTenantMap = rawTenants.first as Map<String, dynamic>;
        }
      }

      final realTenantId = selectedTenantMap?['id']?.toString() ??
          response['tenant_id']?.toString() ??
          (cleanSubdomain.isNotEmpty ? cleanSubdomain : 'default_tenant');
      final realTenantSlug = selectedTenantMap?['slug']?.toString() ?? cleanSubdomain;
      final realTenantName =
          selectedTenantMap?['name']?.toString() ?? response['tenant_name']?.toString();
      final userId = meData['id']?.toString() ?? response['user_id']?.toString();
      final userName = meData['full_name']?.toString() ?? meData['name']?.toString();
      final userEmail = meData['email']?.toString() ?? email;

      await _tokenStore.saveAuth(
        accessToken: accessToken,
        refreshToken: refreshToken,
        tenantId: realTenantId,
        tenantSubdomain: realTenantSlug,
        userId: userId,
        userEmail: userEmail,
        userName: userName,
      );

      final userJson = {
        ...response,
        if (meData.isNotEmpty) ...meData,
        'tenant_id': realTenantId,
        'tenant_name': realTenantName,
        'tenant_slug': realTenantSlug,
      };

      return AuthUser.fromJson(userJson);
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
        final savedTenantId = await _tokenStore.getTenantId();
        return AuthUser.fromJson({
          ...response,
          if (savedTenantId != null && savedTenantId.isNotEmpty) 'tenant_id': savedTenantId,
        });
      }
    } catch (_) {
      // Never synthesize fake credentials when backend verification fails
      return null;
    }
    return null;
  }

  Future<void> logout() async {
    try {
      final refreshToken = await _tokenStore.getRefreshToken();
      await _apiClient.post(
        ApiEndpoints.logout,
        body: {
          if (refreshToken != null && refreshToken.isNotEmpty) 'refresh_token': refreshToken,
        },
      );
    } catch (_) {}
    await _tokenStore.clear();
  }

  Future<bool> isLoggedIn() => _tokenStore.isAuthenticated();
  Future<String?> getSavedSubdomain() => _tokenStore.getTenantSubdomain();
}
