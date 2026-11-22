import type { LogRecord } from '@/shared/log'

export type PlatformKind = 'tauri' | 'noop'

export interface AppInfo {
  readonly productName: string
  readonly version: string
  readonly identifier: string
  readonly os: 'windows' | 'macos' | 'linux' | 'unknown'
}

/** What the shell can tell us and do. */
export interface ShellPort {
  appInfo(): Promise<AppInfo>
  openCustomerDisplay(): Promise<boolean>
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
  saveApiBaseUrl?(url: string): Promise<boolean>
}

export interface PrinterDevice {
  readonly name: string
  readonly vendorId?: number
  readonly productId?: number
}

export interface PrinterPort {
  listPrinters(): Promise<PrinterDevice[]>
  printRaw(data: Uint8Array): Promise<void>
  openCashDrawer(printerName?: string): Promise<void>
}

export interface UpdateCheckResult {
  readonly available: boolean
  readonly version?: string
  readonly date?: string
  readonly body?: string
}

export interface UpdaterPort {
  check(): Promise<UpdateCheckResult>
  downloadAndInstall(): Promise<void>
}

export interface AuthUser {
  readonly id: string
  readonly name: string
  readonly email: string
  readonly role: string
  readonly permissions: readonly string[]
}

export interface AuthTenant {
  readonly id: string
  readonly name: string
  readonly subdomain: string
  readonly currency?: string
}

export interface AuthBranch {
  readonly id: string
  readonly name: string
}

export interface AuthRegister {
  readonly id: string
  readonly name: string
}

export interface AuthSession {
  readonly token: string
  readonly refreshToken?: string
  readonly user: AuthUser
  readonly tenant: AuthTenant
  readonly branch?: AuthBranch
  readonly register?: AuthRegister
}

export interface LoginCredentials {
  readonly email: string
  readonly password: string
  readonly subdomain?: string
}

export interface AuthPort {
  getSession(): Promise<AuthSession | null>
  login(credentials: LoginCredentials): Promise<AuthSession>
  logout(): Promise<void>
  switchBranch(branch: AuthBranch): Promise<void>
  switchRegister(register: AuthRegister): Promise<void>
}

export interface HttpRequestOptions {
  readonly method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  readonly headers?: Record<string, string>
  readonly body?: unknown
}

export interface HttpPort {
  request<T = unknown>(endpoint: string, options?: HttpRequestOptions): Promise<T>
}

export interface Platform {
  readonly kind: PlatformKind
  readonly shell: ShellPort
  readonly log: LogPort
  readonly runtime: RuntimePort
  readonly printer: PrinterPort
  readonly updater: UpdaterPort
  readonly auth: AuthPort
  readonly http: HttpPort
}

export interface NoopPlatformOptions {
  readonly onLog?: (record: LogRecord) => void
  readonly apiBaseUrl?: string | null
  readonly initialSession?: AuthSession | null
}
