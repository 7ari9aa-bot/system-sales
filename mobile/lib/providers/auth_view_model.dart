import 'package:flutter/material.dart';
import '../core/api/api_client.dart';
import '../core/auth/auth_token_store.dart';
import '../core/auth/biometric_service.dart';
import '../data/models/branch.dart';
import '../data/models/user.dart';
import '../data/repositories/auth_repository.dart';

class AuthViewModel extends ChangeNotifier {
  AuthViewModel({
    AuthRepository? authRepository,
    BiometricService? biometricService,
    AuthTokenStore? tokenStore,
  })  : _authRepository = authRepository ?? AuthRepository(),
        _biometricService = biometricService ?? BiometricService(),
        _tokenStore = tokenStore ?? AuthTokenStore() {
    _activeBranch = _availableBranches.first;
  }

  final AuthRepository _authRepository;
  final BiometricService _biometricService;
  final AuthTokenStore _tokenStore;

  AuthUser? _currentUser;
  bool _isLoading = false;
  String? _errorMessage;
  bool _isInitialized = false;
  bool _isBiometricAvailable = false;
  bool _isBiometricEnabled = false;

  final List<Branch> _availableBranches = const [
    Branch(
      id: 'br_main',
      name: 'الفرع الرئيسي - الرياض',
      code: 'RUH-01',
      location: 'طريق العليا، الرياض',
      isMain: true,
    ),
    Branch(
      id: 'br_jeddah',
      name: 'فرع جدة - الشاطئ',
      code: 'JED-01',
      location: 'طريق الملك عبدالعزيز، جدة',
      isMain: false,
    ),
    Branch(
      id: 'br_khobar',
      name: 'فرع الخبر - الظهران',
      code: 'KHB-01',
      location: 'طريق الملك فيصل، الخبر',
      isMain: false,
    ),
  ];

  late Branch _activeBranch;

  AuthUser? get currentUser => _currentUser;
  bool get isLoading => _isLoading;
  String? get errorMessage => _errorMessage;
  bool get isAuthenticated => _currentUser != null;
  bool get isInitialized => _isInitialized;
  bool get isBiometricAvailable => _isBiometricAvailable;
  bool get isBiometricEnabled => _isBiometricEnabled;
  List<Branch> get availableBranches => _availableBranches;
  Branch get activeBranch => _activeBranch;

  bool _isTerminalLocked = false;
  String _terminalPin = '1234';
  bool get isTerminalLocked => _isTerminalLocked;

  void setTerminalPin(String pin) {
    if (pin.trim().length >= 4) {
      _terminalPin = pin.trim();
      _tokenStore.savePin(_terminalPin);
    }
  }

  void lockTerminal() {
    _isTerminalLocked = true;
    notifyListeners();
  }

  bool unlockTerminal(String pin) {
    if (pin.trim() == _terminalPin) {
      _isTerminalLocked = false;
      notifyListeners();
      return true;
    }
    return false;
  }

  bool hasPermission(String permission) {
    if (_currentUser == null) return false;
    final role = _currentUser!.role?.toLowerCase();
    if (role == 'owner' || role == 'admin' || role == 'manager') return true;
    if (_currentUser!.permissions.contains('*')) return true;
    return _currentUser!.permissions.contains(permission);
  }

  bool get canApplyDiscounts => hasPermission('pos:discount') || hasPermission('pos:write');
  bool get canCloseShift => hasPermission('pos:shift_close') || hasPermission('pos:write');
  bool get canViewReports => hasPermission('reports:read');
  bool get canManageInventory => hasPermission('inventory:write');
  bool get canManageSettings => hasPermission('settings:manage');

  void switchBranch(Branch branch) {
    _activeBranch = branch;
    notifyListeners();
  }

  Future<void> checkAuthStatus() async {
    _isLoading = true;
    notifyListeners();

    try {
      final savedPin = await _tokenStore.getPin();
      if (savedPin != null && savedPin.isNotEmpty) {
        _terminalPin = savedPin;
      }
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
    String tenantSubdomain = '',
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
      if (e is ApiException) {
        _errorMessage = e.message;
      } else {
        _errorMessage = e.toString().replaceFirst('Exception: ', '').replaceFirst('ApiException: ', '');
      }
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
      _errorMessage = 'انتهت صلاحية الجلسة، يرجى إعادة تسجيل الدخول بكلمة المرور';
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
