class AuthUser {
  final String id;
  final String email;
  final String? name;
  final String? role;
  final String tenantId;
  final String? tenantName;
  final List<String> permissions;

  const AuthUser({
    required this.id,
    required this.email,
    this.name,
    this.role,
    required this.tenantId,
    this.tenantName,
    this.permissions = const [],
  });

  factory AuthUser.fromJson(Map<String, dynamic> json) {
    return AuthUser(
      id: json['id']?.toString() ?? '',
      email: json['email']?.toString() ?? '',
      name: json['name']?.toString() ?? json['full_name']?.toString(),
      role: json['role']?.toString(),
      tenantId: json['tenant_id']?.toString() ?? '',
      tenantName: json['tenant_name']?.toString(),
      permissions: (json['permissions'] as List<dynamic>?)
              ?.map((e) => e.toString())
              .toList() ??
          const [],
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'email': email,
        'name': name,
        'role': role,
        'tenant_id': tenantId,
        'tenant_name': tenantName,
        'permissions': permissions,
      };
}
