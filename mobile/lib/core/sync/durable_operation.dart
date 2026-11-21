import 'dart:convert';

/// Status lifecycle per the Master Plan:
/// PENDING -> SENDING -> ACKNOWLEDGED
/// or:
/// PENDING -> SENDING -> CONFLICT / REJECTED
enum DurableOperationStatus {
  pending,
  sending,
  acknowledged,
  conflict,
  rejected;

  String toDbString() {
    switch (this) {
      case DurableOperationStatus.pending:
        return 'PENDING';
      case DurableOperationStatus.sending:
        return 'SENDING';
      case DurableOperationStatus.acknowledged:
        return 'ACKNOWLEDGED';
      case DurableOperationStatus.conflict:
        return 'CONFLICT';
      case DurableOperationStatus.rejected:
        return 'REJECTED';
    }
  }

  static DurableOperationStatus fromDbString(String str) {
    switch (str.toUpperCase()) {
      case 'SENDING':
        return DurableOperationStatus.sending;
      case 'ACKNOWLEDGED':
        return DurableOperationStatus.acknowledged;
      case 'CONFLICT':
        return DurableOperationStatus.conflict;
      case 'REJECTED':
        return DurableOperationStatus.rejected;
      case 'PENDING':
      default:
        return DurableOperationStatus.pending;
    }
  }
}

class DurableOperation {
  final String operationUuid;
  final String tenantId;
  final String userId;
  final String deviceId;
  final String? registerId;
  final String operationType;
  final Map<String, dynamic> payloadSnapshot;
  final String idempotencyKey;
  final DateTime createdAt;
  final int schemaVersion;
  final DurableOperationStatus status;
  final int retryCount;
  final DateTime? lastAttemptAt;
  final String? errorMessage;

  DurableOperation({
    required this.operationUuid,
    required this.tenantId,
    required this.userId,
    required this.deviceId,
    this.registerId,
    required this.operationType,
    required this.payloadSnapshot,
    required this.idempotencyKey,
    required this.createdAt,
    this.schemaVersion = 1,
    this.status = DurableOperationStatus.pending,
    this.retryCount = 0,
    this.lastAttemptAt,
    this.errorMessage,
  });

  Map<String, dynamic> toMap() => {
        'operation_uuid': operationUuid,
        'tenant_id': tenantId,
        'user_id': userId,
        'device_id': deviceId,
        'register_id': registerId,
        'operation_type': operationType,
        'payload_snapshot': jsonEncode(payloadSnapshot),
        'idempotency_key': idempotencyKey,
        'created_at': createdAt.toIso8601String(),
        'schema_version': schemaVersion,
        'status': status.toDbString(),
        'retry_count': retryCount,
        'last_attempt_at': lastAttemptAt?.toIso8601String(),
        'error_message': errorMessage,
      };

  factory DurableOperation.fromMap(Map<String, dynamic> map) {
    Map<String, dynamic> payload = {};
    try {
      final rawSnapshot = map['payload_snapshot'];
      if (rawSnapshot is String) {
        payload = jsonDecode(rawSnapshot) as Map<String, dynamic>;
      } else if (rawSnapshot is Map) {
        payload = Map<String, dynamic>.from(rawSnapshot);
      }
    } catch (_) {}

    return DurableOperation(
      operationUuid: map['operation_uuid']?.toString() ?? '',
      tenantId: map['tenant_id']?.toString() ?? '',
      userId: map['user_id']?.toString() ?? '',
      deviceId: map['device_id']?.toString() ?? '',
      registerId: map['register_id']?.toString(),
      operationType: map['operation_type']?.toString() ?? 'unknown',
      payloadSnapshot: payload,
      idempotencyKey: map['idempotency_key']?.toString() ?? '',
      createdAt: map['created_at'] != null
          ? DateTime.tryParse(map['created_at'].toString()) ?? DateTime.now()
          : DateTime.now(),
      schemaVersion: (map['schema_version'] as num?)?.toInt() ?? 1,
      status: DurableOperationStatus.fromDbString(map['status']?.toString() ?? 'PENDING'),
      retryCount: (map['retry_count'] as num?)?.toInt() ?? 0,
      lastAttemptAt: map['last_attempt_at'] != null
          ? DateTime.tryParse(map['last_attempt_at'].toString())
          : null,
      errorMessage: map['error_message']?.toString(),
    );
  }
}
