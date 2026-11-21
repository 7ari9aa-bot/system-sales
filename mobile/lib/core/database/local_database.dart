import 'dart:async';
import 'package:path/path.dart';
import 'package:sqflite/sqflite.dart';

/// Local SQLite Database for Fihrist Native Clients.
/// Adheres strictly to Section 5 of the Master Plan:
/// - Durable Operation Queue
/// - Tenant isolation and attribution
/// - Idempotency keys and schema versioning
class LocalDatabase {
  static final LocalDatabase instance = LocalDatabase._init();
  static Database? _database;

  LocalDatabase._init();

  Future<Database> get database async {
    if (_database != null) return _database!;
    _database = await _initDB('fihrist_workstation.db');
    return _database!;
  }

  Future<Database> _initDB(String filePath) async {
    final dbPath = await getDatabasesPath();
    final path = join(dbPath, filePath);

    return await openDatabase(
      path,
      version: 1,
      onCreate: _createDB,
    );
  }

  Future<void> _createDB(Database db, int version) async {
    // 1. Durable Operations Queue
    await db.execute('''
      CREATE TABLE durable_operations (
        operation_uuid TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        device_id TEXT NOT NULL,
        register_id TEXT,
        operation_type TEXT NOT NULL,
        payload_snapshot TEXT NOT NULL,
        idempotency_key TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        schema_version INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'PENDING',
        retry_count INTEGER NOT NULL DEFAULT 0,
        last_attempt_at TEXT,
        error_message TEXT
      )
    ''');

    // 2. Index for high-speed tenant-scoped sync lookups
    await db.execute('''
      CREATE INDEX idx_durable_ops_tenant_status 
      ON durable_operations(tenant_id, status)
    ''');

    // 3. Local Product Catalog Cache
    await db.execute('''
      CREATE TABLE cached_products (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        name TEXT NOT NULL,
        sku TEXT,
        barcode TEXT,
        price TEXT NOT NULL,
        cost_price TEXT,
        stock_quantity INTEGER NOT NULL DEFAULT 0,
        category TEXT,
        updated_at TEXT NOT NULL
      )
    ''');

    await db.execute('''
      CREATE INDEX idx_cached_products_barcode 
      ON cached_products(tenant_id, barcode)
    ''');
  }

  Future<void> close() async {
    final db = _database;
    if (db != null) {
      await db.close();
      _database = null;
    }
  }
}
