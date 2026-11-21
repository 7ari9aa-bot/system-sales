import 'package:flutter/material.dart';
import '../core/auth/auth_token_store.dart';
import '../core/auth/biometric_service.dart';
import '../data/models/user.dart';
import '../data/repositories/auth_repository.dart';

class AuthViewModel extends ChangeNotifier {
  AuthViewModel({
    AuthRepository? authRepository,
    BiometricService? biometricService,
    AuthTokenStore? tokenStore,
  })  : _authRepository = authRepository ?? AuthRepository(),
        _biometricService = biometricService ?? BiometricService(),
        _tokenStore = tokenStore ?? AuthTokenStore();

  final AuthRepository _authRepository;
  final BiometricService _biometricService;
  final AuthTokenStore _tokenStore;

  AuthUser? _currentUser;
  bool _isLoading = false;
  String? _errorMessage;
  bool _isInitialized = false;
  bool _isBiometricAvailable = false;
  bool _isBiometricEnabled = false;

  AuthUser? get currentUser => _currentUser;
  bool get isLoading => _isLoading;
  String? get errorMessage => _errorMessage;
  bool get isAuthenticated => _currentUser != null;
  bool get isInitialized => _isInitialized;
  bool get isBiometricAvailable => _isBiometricAvailable;
  bool get isBiometricEnabled => _isBiometricEnabled;

  Future<void> checkAuthStatus() async {
    _isLoading = true;
    notifyListeners();

    try {
      _currentUser = await _authRepository.getCurrentUser();
      await checkBiometricStatus();
    } catch (_) {
      _currentUser = null;
    } finally {
      _isLoading = false;
      _isInitialized = true;
      notifyListeners();
    }
  }

  Future<void> checkBiometricStatus() async {
    _isBiometricAvailable = await _biometricService.isBiometricAvailable();
    _isBiometricEnabled = await _biometricService.isBiometricLoginEnabled();
    notifyListeners();
  }

  Future<void> setBiometricEnabled(bool enabled) async {
    await _biometricService.setBiometricLoginEnabled(enabled);
    _isBiometricEnabled = enabled;
    notifyListeners();
  }

  Future<bool> login({
    required String tenantSubdomain,
    required String email,
    required String password,
  }) async {
    _isLoading = true;
    _errorMessage = null;
    notifyListeners();

    try {
      _currentUser = await _authRepository.login(
        tenantSubdomain: tenantSubdomain,
        email: email,
        password: password,
      );
      await checkBiometricStatus();
      return true;
    } catch (e) {
      _errorMessage = e.toString().replaceFirst('ApiException: ', '');
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<bool> loginWithBiometrics() async {
    if (!_isBiometricAvailable || !_isBiometricEnabled) return false;

    final authenticated = await _biometricService.authenticate(
      localizedReason: 'تأكيد البصمة للدخول إلى حساب نقطة البيع',
    );

    if (!authenticated) return false;

    _isLoading = true;
    _errorMessage = null;
    notifyListeners();

    try {
      // Re-verify token or re-fetch user details
      final user = await _authRepository.getCurrentUser();
      if (user != null) {
        _currentUser = user;
        return true;
      }

      // If token expired but saved credentials exist, construct user session
      final email = await _tokenStore.getUserEmail();
      final tenantId = await _tokenStore.getTenantId();
      if (email != null && tenantId != null) {
        _currentUser = AuthUser(
          id: 'usr-${tenantId.hashCode}',
          email: email,
          name: await _tokenStore.getUserName() ?? 'مسؤول المبيعات',
          role: 'owner',
          tenantId: tenantId,
          tenantName: await _tokenStore.getTenantSubdomain() ?? 'متجر فهرست',
        );
        return true;
      }
      return false;
    } catch (e) {
      _errorMessage = 'فشل تسجيل الدخول بالبصمة: $e';
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> logout() async {
    _isLoading = true;
    notifyListeners();

    await _authRepository.logout();
    _currentUser = null;
    _isLoading = false;
    notifyListeners();
  }
}
