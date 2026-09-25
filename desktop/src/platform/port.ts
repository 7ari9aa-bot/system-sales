import type { LogRecord } from '@/shared/log'

export type PlatformKind = 'tauri' | 'noop'

export interface AppInfo {
  readonly productName: string
  readonly version: string
  readonly identifier: string
  readonly os: 'windows' | 'macos' | 'linux' | 'unknown'
}

/** What the shell can tell us and do. Window management itself is Phase 2. */
export interface ShellPort {
  appInfo(): Promise<AppInfo>
}

/**
 * One-way out: the UI never reads logs back. `write` must never throw — a log
 * line is not worth a broken screen — and the record arrives already redacted by
 * `createLogger`, so the adapter only has to transport it.
 */
export interface LogPort {
  write(record: LogRecord): void
}

/**
 * Phase 0 resolves to `null` unless a developer supplied an address: reading the
 * on-disk settings file needs the native config command, which is Phase 1 work
 * alongside the transport that consumes it.
 */
export interface RuntimePort {
  apiBaseUrl(): Promise<string | null>
}

export interface Platform {
  readonly kind: PlatformKind
  readonly shell: ShellPort
  readonly log: LogPort
  readonly runtime: RuntimePort
}

export interface NoopPlatformOptions {
  readonly onLog?: (record: LogRecord) => void
  readonly apiBaseUrl?: string | null
}
