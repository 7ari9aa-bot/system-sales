import 'dart:convert';
import 'package:http/http.dart' as http;
import '../auth/auth_token_store.dart';
import 'api_endpoints.dart';

class ApiException implements Exception {
  final int statusCode;
  final String message;
  final dynamic details;

  ApiException({
    required this.statusCode,
    required this.message,
    this.details,
  });

  @override
  String toString() => 'ApiException($statusCode): $message';
}

class ApiClient {
  ApiClient({
    http.Client? httpClient,
    AuthTokenStore? tokenStore,
  })  : _http = httpClient ?? http.Client(),
        _tokenStore = tokenStore ?? AuthTokenStore();

  final http.Client _http;
  final AuthTokenStore _tokenStore;

  Future<String> getBaseUrl() => _getBaseUrl();
  Future<void> setBaseUrl(String url) => _tokenStore.setBaseUrl(url);

  Future<String> _getBaseUrl() async {
    final customUrl = await _tokenStore.getBaseUrl();
    if (customUrl != null && customUrl.isNotEmpty) {
      return customUrl;
    }
    return ApiEndpoints.defaultBaseUrl;
  }

  Future<http.Response> _safeSend(
    Future<http.Response> Function() request,
    String baseUrl,
  ) async {
    try {
      return await request();
    } on http.ClientException catch (e) {
      final msg = e.message.toLowerCase();
      if (msg.contains('failed host lookup') || msg.contains('no address associated')) {
        throw ApiException(
          statusCode: 0,
          message: 'تعذر الاتصال بالخادم ($baseUrl). يرجى التأكد من اتصال الإنترنت أو تعديل عنوان الخادم في الإعدادات.',
        );
      } else if (msg.contains('connection refused')) {
        throw ApiException(
          statusCode: 0,
          message: 'تم رفض الاتصال بالخادم ($baseUrl). تأكد من أن الخادم يعمل.',
        );
      }
      throw ApiException(
        statusCode: 0,
        message: 'خطأ في الاتصال بالشبكة: ${e.message}',
      );
    } catch (e) {
      if (e is ApiException) rethrow;
      throw ApiException(
        statusCode: 0,
        message: 'تعذر إتمام الاتصال بالخادم: $e',
      );
    }
  }

  Future<Map<String, String>> _buildHeaders({
    bool includeAuth = true,
    Map<String, String>? extraHeaders,
  }) async {
    final headers = <String, String>{
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    };

    if (includeAuth) {
      final token = await _tokenStore.getAccessToken();
      if (token != null && token.isNotEmpty) {
        headers['Authorization'] = 'Bearer $token';
      }

      final tenantId = await _tokenStore.getTenantId();
      if (tenantId != null && tenantId.isNotEmpty) {
        headers['X-Tenant-Id'] = tenantId;
      }

      final subdomain = await _tokenStore.getTenantSubdomain();
      if (subdomain != null && subdomain.isNotEmpty) {
        headers['X-Tenant-Subdomain'] = subdomain;
      }
    }

    if (extraHeaders != null) {
      headers.addAll(extraHeaders);
    }

    return headers;
  }

  Future<dynamic> get(
    String endpoint, {
    Map<String, String>? queryParams,
    bool includeAuth = true,
    Map<String, String>? extraHeaders,
  }) async {
    final baseUrl = await _getBaseUrl();
    final uri = Uri.parse('$baseUrl$endpoint').replace(queryParameters: queryParams);
    final headers = await _buildHeaders(includeAuth: includeAuth, extraHeaders: extraHeaders);

    final response = await _safeSend(() => _http.get(uri, headers: headers), baseUrl);
    return _handleResponse(response);
  }

  Future<dynamic> post(
    String endpoint, {
    Map<String, dynamic>? body,
    bool includeAuth = true,
    Map<String, String>? extraHeaders,
  }) async {
    final baseUrl = await _getBaseUrl();
    final uri = Uri.parse('$baseUrl$endpoint');
    final headers = await _buildHeaders(includeAuth: includeAuth, extraHeaders: extraHeaders);

    final response = await _safeSend(
      () => _http.post(
        uri,
        headers: headers,
        body: body != null ? jsonEncode(body) : null,
      ),
      baseUrl,
    );
    return _handleResponse(response);
  }

  Future<dynamic> put(
    String endpoint, {
    Map<String, dynamic>? body,
    bool includeAuth = true,
    Map<String, String>? extraHeaders,
  }) async {
    final baseUrl = await _getBaseUrl();
    final uri = Uri.parse('$baseUrl$endpoint');
    final headers = await _buildHeaders(includeAuth: includeAuth, extraHeaders: extraHeaders);

    final response = await _safeSend(
      () => _http.put(
        uri,
        headers: headers,
        body: body != null ? jsonEncode(body) : null,
      ),
      baseUrl,
    );
    return _handleResponse(response);
  }

  Future<dynamic> patch(
    String endpoint, {
    Map<String, dynamic>? body,
    bool includeAuth = true,
    Map<String, String>? extraHeaders,
  }) async {
    final baseUrl = await _getBaseUrl();
    final uri = Uri.parse('$baseUrl$endpoint');
    final headers = await _buildHeaders(includeAuth: includeAuth, extraHeaders: extraHeaders);

    final response = await _safeSend(
      () => _http.patch(
        uri,
        headers: headers,
        body: body != null ? jsonEncode(body) : null,
      ),
      baseUrl,
    );
    return _handleResponse(response);
  }

  Future<dynamic> delete(
    String endpoint, {
    bool includeAuth = true,
    Map<String, String>? extraHeaders,
  }) async {
    final baseUrl = await _getBaseUrl();
    final uri = Uri.parse('$baseUrl$endpoint');
    final headers = await _buildHeaders(includeAuth: includeAuth, extraHeaders: extraHeaders);

    final response = await _safeSend(() => _http.delete(uri, headers: headers), baseUrl);
    return _handleResponse(response);
  }

  dynamic _handleResponse(http.Response response) {
    if (response.statusCode >= 200 && response.statusCode < 300) {
      if (response.body.isEmpty) return null;
      try {
        return jsonDecode(response.body);
      } catch (_) {
        return response.body;
      }
    }

    String errorMessage = 'Request failed with status: ${response.statusCode}';
    dynamic errorDetails;

    try {
      final decoded = jsonDecode(response.body);
      if (decoded is Map<String, dynamic>) {
        errorMessage = decoded['detail']?.toString() ??
            decoded['message']?.toString() ??
            errorMessage;
        errorDetails = decoded;
      }
    } catch (_) {
      errorMessage = response.body.isNotEmpty ? response.body : errorMessage;
    }

    throw ApiException(
      statusCode: response.statusCode,
      message: errorMessage,
      details: errorDetails,
    );
  }
}
