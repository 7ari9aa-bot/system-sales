class TenantMembership {
  final String id; // UUID
  final String name;
  final String slug;
  final String roleCode;
  final String currency;

  const TenantMembership({
    required this.id,
    required this.name,
    required this.slug,
    required this.roleCode,
    this.currency = 'SAR',
  });

  factory TenantMembership.fromJson(Map<String, dynamic> json) {
    return TenantMembership(
      id: json['id']?.toString() ?? '',
      name: json['name']?.toString() ?? '',
      slug: json['slug']?.toString() ?? '',
      roleCode: json['role_code']?.toString() ?? json['role']?.toString() ?? 'cashier',
      currency: json['currency']?.toString() ?? 'SAR',
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'slug': slug,
        'role_code': roleCode,
        'currency': currency,
      };
}

class AuthUser {
  final String id;
  final String email;
  final String? name;
  final String? role;
  final String tenantId;
  final String? tenantName;
  final String? tenantSlug;
  final List<TenantMembership> tenants;
  final List<String> permissions;

  const AuthUser({
    required this.id,
    required this.email,
    this.name,
    this.role,
    required this.tenantId,
    this.tenantName,
    this.tenantSlug,
    this.tenants = const [],
    this.permissions = const [],
  });

  factory AuthUser.fromJson(Map<String, dynamic> json) {
    final rawTenants = (json['tenants'] as List<dynamic>?)
            ?.map((e) => TenantMembership.fromJson(e as Map<String, dynamic>))
            .toList() ??
        const [];

    TenantMembership? activeTenant;
    if (rawTenants.isNotEmpty) {
      final targetId = json['tenant_id']?.toString();
      if (targetId != null && targetId.isNotEmpty) {
        activeTenant = rawTenants.firstWhere(
          (t) => t.id == targetId,
          orElse: () => rawTenants.first,
        );
      } else {
        activeTenant = rawTenants.first;
      }
    }

    final effectiveTenantId = json['tenant_id']?.toString() ?? activeTenant?.id ?? '';
    final effectiveTenantName = json['tenant_name']?.toString() ?? activeTenant?.name;
    final effectiveRole = json['role']?.toString() ?? activeTenant?.roleCode ?? 'cashier';

    return AuthUser(
      id: json['id']?.toString() ?? '',
      email: json['email']?.toString() ?? '',
      name: json['name']?.toString() ?? json['full_name']?.toString(),
      role: effectiveRole,
      tenantId: effectiveTenantId,
      tenantName: effectiveTenantName,
      tenantSlug: activeTenant?.slug,
      tenants: rawTenants,
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
        'tenant_slug': tenantSlug,
        'tenants': tenants.map((t) => t.toJson()).toList(),
        'permissions': permissions,
      };
}
