import { z } from 'zod'

import { call } from './invoke'
import type {
  AppInfo,
  AuthBranch,
  AuthPort,
  AuthRegister,
  AuthSession,
  HttpPort,
  HttpRequestOptions,
  LoginCredentials,
  LogPort,
  Platform,
  PrinterDevice,
  PrinterPort,
  RuntimePort,
  ShellPort,
  UpdateCheckResult,
  UpdaterPort,
} from '../port'
import type { LogRecord } from '@/shared/log'

const appInfoSchema = z.object({
  productName: z.string().min(1),
  version: z.string().min(1),
  identifier: z.string().min(1),
  os: z.enum(['windows', 'macos', 'linux', 'unknown']),
})

const shell: ShellPort = {
  async appInfo(): Promise<AppInfo> {
    return appInfoSchema.parse(await call('app_info'))
  },
  async openCustomerDisplay(): Promise<boolean> {
    try {
      await call('open_customer_display')
      return true
    } catch {
      return false
    }
  },
}

const log: LogPort = {
  write(record: LogRecord): void {
    void call('log_write', {
      record: {
        level: record.level,
        message: record.message,
        fields: record.fields,
        requestId: record.requestId,
        sink: record.sink,
        ts: record.ts,
      },
    }).catch(() => {
      // The native logger is unavailable. Dropping a line beats dropping a screen.
    })
  },
}

const runtime: RuntimePort = {
  /**
   * Phase 1 replaces this with a read of the on-disk settings file. A dev-only
   * value is the only thing that can be honoured before that exists, and it is
   * read in `DEV` alone: a production bundle must contain no host at all
   * (config/check-no-hardcoded-host.mjs is the gate that proves it).
   */
  async apiBaseUrl(): Promise<string | null> {
    try {
      const settings = await call('read_settings')
      if (typeof settings === 'string' && settings.trim() !== '') {
        return settings
      }
    } catch {
      // Settings file absent or unreadable
    }

    if (!import.meta.env.DEV) return null
    const configured: unknown = import.meta.env.FH_API_BASE_URL

    return typeof configured === 'string' && configured.trim() !== '' ? configured : null
  },
  async saveApiBaseUrl(url: string): Promise<boolean> {
    try {
      await call('write_settings', { webAppUrl: url })
      return true
    } catch {
      return false
    }
  },
}

const printer: PrinterPort = {
  async listPrinters(): Promise<PrinterDevice[]> {
    try {
      const res = await call('list_printers')
      return Array.isArray(res) ? (res as PrinterDevice[]) : []
    } catch {
      return []
    }
  },
  async printRaw(data: Uint8Array): Promise<void> {
    await call('print_raw', { data: Array.from(data) })
  },
  async openCashDrawer(printerName?: string): Promise<void> {
    await call('open_cash_drawer', { printerName })
  },
}

const updater: UpdaterPort = {
  async check(): Promise<UpdateCheckResult> {
    try {
      const res = (await call('check_update')) as UpdateCheckResult | undefined
      return res?.available !== undefined ? res : { available: false }
    } catch {
      return { available: false }
    }
  },
  async downloadAndInstall(): Promise<void> {
    await call('install_update')
  },
}

const authSessionSchema = z.object({
  token: z.string().min(1),
  user: z.object({
    id: z.string(),
    name: z.string(),
    email: z.string(),
    role: z.string(),
    permissions: z.array(z.string()),
  }),
  tenant: z.object({
    id: z.string(),
    name: z.string(),
    subdomain: z.string(),
  }),
  branch: z
    .object({
      id: z.string(),
      name: z.string(),
    })
    .optional(),
  register: z
    .object({
      id: z.string(),
      name: z.string(),
    })
    .optional(),
})

let cachedSession: AuthSession | null = null

const auth: AuthPort = {
  async getSession(): Promise<AuthSession | null> {
    if (cachedSession) return cachedSession
    try {
      const raw = await call('read_auth_session')
      if (!raw) return null
      const parsed = authSessionSchema.parse(JSON.parse(raw))
      cachedSession = parsed
      return parsed
    } catch {
      return null
    }
  },

  async login(credentials: LoginCredentials): Promise<AuthSession> {
    const baseUrl = (await runtime.apiBaseUrl()) || ''
    const url = `${baseUrl.replace(/\/+$/, '')}/api/v1/auth/token`
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    if (credentials.subdomain) {
      headers['X-Tenant-Subdomain'] = credentials.subdomain
    }

    const response = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        email: credentials.email,
        password: credentials.password,
        subdomain: credentials.subdomain,
      }),
    })

    if (!response.ok) {
      const err = await response.text()
      throw new Error(`Login failed (${response.status}): ${err}`)
    }

    const data = (await response.json()) as {
      access_token?: string
      token?: string
      user?: { id?: string; name?: string; email?: string; role?: string; permissions?: string[] }
      tenant?: { id?: string; name?: string; subdomain?: string }
      branch?: { id: string; name: string }
      register?: { id: string; name: string }
    }

    const token = data.access_token || data.token || ''
    if (!token) throw new Error('No token received from login API')

    const session: AuthSession = {
      token,
      user: {
        id: data.user?.id || 'usr_1',
        name: data.user?.name || credentials.email.split('@')[0] || 'User',
        email: data.user?.email || credentials.email,
        role: data.user?.role || 'cashier',
        permissions: data.user?.permissions || ['pos:read', 'pos:write'],
      },
      tenant: {
        id: data.tenant?.id || 't_1',
        name: data.tenant?.name || 'Fihrist Store',
        subdomain: credentials.subdomain || data.tenant?.subdomain || 'shop',
      },
      branch: data.branch || { id: 'br_main', name: 'الفرع الرئيسي' },
      register: data.register || { id: 'reg_1', name: 'نقطة 1' },
    }

    cachedSession = session
    await call('write_auth_session', { sessionJson: JSON.stringify(session) })
    return session
  },

  async logout(): Promise<void> {
    cachedSession = null
    await call('clear_auth_session')
  },

  async switchBranch(branch: AuthBranch): Promise<void> {
    const session = await auth.getSession()
    if (!session) return
    const updated: AuthSession = { ...session, branch }
    cachedSession = updated
    await call('write_auth_session', { sessionJson: JSON.stringify(updated) })
  },

  async switchRegister(register: AuthRegister): Promise<void> {
    const session = await auth.getSession()
    if (!session) return
    const updated: AuthSession = { ...session, register }
    cachedSession = updated
    await call('write_auth_session', { sessionJson: JSON.stringify(updated) })
  },
}

const http: HttpPort = {
  async request<T = unknown>(endpoint: string, options: HttpRequestOptions = {}): Promise<T> {
    const baseUrl = (await runtime.apiBaseUrl()) || ''
    const session = await auth.getSession()
    const url = endpoint.startsWith('http')
      ? endpoint
      : `${baseUrl.replace(/\/+$/, '')}/${endpoint.replace(/^\/+/, '')}`

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...options.headers,
    }

    if (session?.token) {
      headers['Authorization'] = `Bearer ${session.token}`
    }
    if (session?.tenant?.subdomain) {
      headers['X-Tenant-Subdomain'] = session.tenant.subdomain
    }
    if (session?.tenant?.id) {
      headers['X-Tenant-Id'] = session.tenant.id
    }
    if (session?.branch?.id) {
      headers['X-Branch-Id'] = session.branch.id
    }

    const res = await fetch(url, {
      method: options.method || 'GET',
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    })

    if (!res.ok) {
      if (res.status === 401) {
        await auth.logout()
      }
      const errorText = await res.text()
      throw new Error(`HTTP Error ${res.status}: ${errorText}`)
    }

    return (await res.json()) as T
  },
}

export function createTauriPlatform(): Platform {
  return { kind: 'tauri', shell, log, runtime, printer, updater, auth, http }
}
