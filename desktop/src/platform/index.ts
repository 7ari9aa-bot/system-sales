import { createNoopPlatform } from './noop'
import type { NoopPlatformOptions, Platform } from './port'

export type {
  AppInfo,
  AuthBranch,
  AuthPort,
  AuthRegister,
  AuthSession,
  AuthTenant,
  AuthUser,
  HttpPort,
  HttpRequestOptions,
  LoginCredentials,
  LogPort,
  NoopPlatformOptions,
  Platform,
  PrinterDevice,
  PrinterPort,
  RuntimePort,
  ShellPort,
  UpdateCheckResult,
  UpdaterPort,
} from './port'
export { createNoopPlatform }

interface TauriInternals {
  invoke?: unknown
}

function hasNativeBridge(): boolean {
  const w = globalThis as unknown as { __TAURI_INTERNALS__?: TauriInternals }

  return typeof w.__TAURI_INTERNALS__?.invoke === 'function'
}

/**
 * Decided once, at bootstrap, and passed down. Nothing in the tree asks the
 * platform a second time, so a component can never branch on which runtime it
 * happens to be mounted in.
 */
export async function resolvePlatform(options: NoopPlatformOptions = {}): Promise<Platform> {
  if (!hasNativeBridge()) return createNoopPlatform(options)

  const { createTauriPlatform } = await import('./tauri')

  return createTauriPlatform()
}
