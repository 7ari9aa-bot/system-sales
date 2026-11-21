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

  Future<String> _getBaseUrl() async {
    final customUrl = await _tokenStore.getBaseUrl();
    if (customUrl != null && customUrl.isNotEmpty) {
      return customUrl;
    }
    return ApiEndpoints.defaultBaseUrl;
  }

  Future<Map<String, String>> _buildHeaders({bool includeAuth = true}) async {
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
    }

    return headers;
  }

  Future<dynamic> get(String endpoint, {Map<String, String>? queryParams, bool includeAuth = true}) async {
    final baseUrl = await _getBaseUrl();
    final uri = Uri.parse('$baseUrl$endpoint').replace(queryParameters: queryParams);
    final headers = await _buildHeaders(includeAuth: includeAuth);

    final response = await _http.get(uri, headers: headers);
    return _handleResponse(response);
  }

  Future<dynamic> post(
    String endpoint, {
    Map<String, dynamic>? body,
    bool includeAuth = true,
  }) async {
    final baseUrl = await _getBaseUrl();
    final uri = Uri.parse('$baseUrl$endpoint');
    final headers = await _buildHeaders(includeAuth: includeAuth);

    final response = await _http.post(
      uri,
      headers: headers,
      body: body != null ? jsonEncode(body) : null,
    );
    return _handleResponse(response);
  }

  Future<dynamic> put(
    String endpoint, {
    Map<String, dynamic>? body,
    bool includeAuth = true,
  }) async {
    final baseUrl = await _getBaseUrl();
    final uri = Uri.parse('$baseUrl$endpoint');
    final headers = await _buildHeaders(includeAuth: includeAuth);

    final response = await _http.put(
      uri,
      headers: headers,
      body: body != null ? jsonEncode(body) : null,
    );
    return _handleResponse(response);
  }

  Future<dynamic> delete(String endpoint, {bool includeAuth = true}) async {
    final baseUrl = await _getBaseUrl();
    final uri = Uri.parse('$baseUrl$endpoint');
    final headers = await _buildHeaders(includeAuth: includeAuth);

    final response = await _http.delete(uri, headers: headers);
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
