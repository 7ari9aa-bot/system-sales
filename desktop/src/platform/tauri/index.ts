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

function buildApiUrl(baseUrl: string, endpoint: string): string {
  const cleanBase = baseUrl.replace(/\/+$/, '')
  const cleanEndpoint = endpoint.replace(/^\/+/, '')

  if (cleanBase.endsWith('/api/v1')) {
    if (cleanEndpoint.startsWith('api/v1/')) {
      return `${cleanBase}/${cleanEndpoint.substring(7)}`
    }
    return `${cleanBase}/${cleanEndpoint}`
  }

  if (cleanEndpoint.startsWith('api/v1/')) {
    return `${cleanBase}/${cleanEndpoint}`
  }

  return `${cleanBase}/api/v1/${cleanEndpoint}`
}

const authSessionSchema = z.object({
  token: z.string().min(1),
  refreshToken: z.string().optional(),
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
    currency: z.string().default('SAR'),
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
    const loginUrl = buildApiUrl(baseUrl, 'auth/login')

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    }
    if (credentials.subdomain) {
      headers['X-Tenant-Subdomain'] = credentials.subdomain
    }

    // 1. Authenticate with email + password -> TokenPair
    const response = await fetch(loginUrl, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        email: credentials.email,
        password: credentials.password,
      }),
    })

    if (!response.ok) {
      const err = await response.text()
      throw new Error(`Login failed (${response.status}): ${err}`)
    }

    const tokenPair = (await response.json()) as {
      access_token: string
      refresh_token?: string
      token_type?: string
      expires_in?: number
    }

    if (!tokenPair.access_token) throw new Error('No access token received from login API')

    // 2. Query /auth/me with Bearer token to discover identity & tenant memberships
    const meUrl = buildApiUrl(baseUrl, 'auth/me')
    const meRes = await fetch(meUrl, {
      headers: {
        Authorization: `Bearer ${tokenPair.access_token}`,
        Accept: 'application/json',
      },
    })

    if (!meRes.ok) {
      const err = await meRes.text()
      throw new Error(`Failed to load user profile (${meRes.status}): ${err}`)
    }

    const meData = (await meRes.json()) as {
      id: string
      email: string
      full_name?: string
      tenants: Array<{
        id: string
        name: string
        slug: string
        role_code?: string
        currency?: string
      }>
    }

    if (!meData.tenants || meData.tenants.length === 0) {
      throw new Error('User has no active store memberships')
    }

    // Select active tenant matching subdomain or first tenant
    let chosenTenant = meData.tenants[0]!
    if (credentials.subdomain) {
      const matched = meData.tenants.find(
        (t) =>
          t.slug.toLowerCase() === credentials.subdomain!.toLowerCase() ||
          t.name.toLowerCase() === credentials.subdomain!.toLowerCase(),
      )
      if (matched) {
        chosenTenant = matched
      }
    }

    let activeAccessToken = tokenPair.access_token
    let activeRefreshToken = tokenPair.refresh_token

    // Switch tenant context on server if needed
    if (chosenTenant && tokenPair.refresh_token) {
      try {
        const switchUrl = buildApiUrl(baseUrl, 'auth/switch-tenant')
        const switchRes = await fetch(switchUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${activeAccessToken}`,
          },
          body: JSON.stringify({
            tenant_id: chosenTenant.id,
            refresh_token: tokenPair.refresh_token,
          }),
        })
        if (switchRes.ok) {
          const switchedPair = (await switchRes.json()) as {
            access_token?: string
            refresh_token?: string
          }
          if (switchedPair.access_token) activeAccessToken = switchedPair.access_token
          if (switchedPair.refresh_token) activeRefreshToken = switchedPair.refresh_token
        }
      } catch {
        // Fall back to original token pair
      }
    }

    // 3. Discover available registers for this tenant
    let activeRegister: AuthRegister | undefined
    try {
      const regUrl = buildApiUrl(baseUrl, 'pos/registers')
      const regRes = await fetch(regUrl, {
        headers: {
          Authorization: `Bearer ${activeAccessToken}`,
          'X-Tenant-Id': chosenTenant.id,
          Accept: 'application/json',
        },
      })
      if (regRes.ok) {
        const regList = (await regRes.json()) as Array<{ id: string; name: string }>
        if (Array.isArray(regList) && regList.length > 0 && regList[0]) {
          activeRegister = { id: regList[0].id, name: regList[0].name }
        }
      }
    } catch {
      // Offline or initial setup fallback
    }

    const session: AuthSession = {
      token: activeAccessToken,
      refreshToken: activeRefreshToken,
      user: {
        id: meData.id,
        name: meData.full_name || meData.email.split('@')[0] || 'User',
        email: meData.email,
        role: chosenTenant.role_code || 'cashier',
        permissions: ['pos:read', 'pos:write', 'inventory:read'],
      },
      tenant: {
        id: chosenTenant.id,
        name: chosenTenant.name,
        subdomain: chosenTenant.slug,
        currency: chosenTenant.currency || 'SAR',
      },
      branch: { id: 'br_main', name: 'الفرع الرئيسي' },
      register: activeRegister,
    }

    cachedSession = session
    await call('write_auth_session', { sessionJson: JSON.stringify(session) })
    return session
  },

  async logout(): Promise<void> {
    const session = cachedSession || (await auth.getSession())
    if (session?.refreshToken) {
      try {
        const baseUrl = (await runtime.apiBaseUrl()) || ''
        const logoutUrl = buildApiUrl(baseUrl, 'auth/logout')
        await fetch(logoutUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${session.token}`,
          },
          body: JSON.stringify({ refresh_token: session.refreshToken }),
        })
      } catch {
        // Continue clearing local session even if server unreachable
      }
    }
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
    const url = endpoint.startsWith('http') ? endpoint : buildApiUrl(baseUrl, endpoint)

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
