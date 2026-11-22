import type { LogRecord } from '@/shared/log'

import type { AppInfo, AuthPort, AuthSession, HttpPort, NoopPlatformOptions, Platform, PrinterPort, UpdaterPort } from './port'

/**
 * Not a stub to be replaced: this is what `vite dev` and every unit test run on.
 * Keeping it honest is what makes the UI testable without a Tauri runtime, and
 * if a bug can only be reproduced on a real window, it is a gap in the real
 * adapter, not an excuse to stop testing.
 */
export function createNoopPlatform(options: NoopPlatformOptions = {}): Platform {
  const info: AppInfo = {
    productName: 'Fihrist',
    version: '0.0.0-web',
    identifier: 'com.fihrist.desktop.web',
    os: 'unknown',
  }

  const write = (record: LogRecord): void => {
    options.onLog?.(record)
  }

  const printer: PrinterPort = {
    listPrinters: () => Promise.resolve([]),
    printRaw: () => Promise.resolve(),
    openCashDrawer: () => Promise.resolve(),
  }

  const updater: UpdaterPort = {
    check: () => Promise.resolve({ available: false }),
    downloadAndInstall: () => Promise.resolve(),
  }

  let currentSession: AuthSession | null =
    options.initialSession !== undefined
      ? options.initialSession
      : {
          token: 'test_mock_token_7788',
          user: {
            id: 'usr_mock_1',
            name: 'أحمد سالم (مدير المتجر)',
            email: 'manager@fihrist.local',
            role: 'owner',
            permissions: ['pos:read', 'pos:write', 'inventory:read', 'inventory:write', 'reports:read', 'team:manage'],
          },
          tenant: {
            id: 't_mock_1',
            name: 'متجر فهرس التجريبي',
            subdomain: 'demo',
          },
          branch: {
            id: 'br_main',
            name: 'الفرع الرئيسي - الرياض',
          },
          register: {
            id: 'reg_01',
            name: 'كاشير نقطة 1',
          },
        }

  const auth: AuthPort = {
    getSession: () => Promise.resolve(currentSession),
    login: (credentials) => {
      currentSession = {
        token: `test_token_${Date.now()}`,
        user: {
          id: 'usr_1',
          name: credentials.email.split('@')[0] || 'المستخدم',
          email: credentials.email,
          role: 'owner',
          permissions: ['*'],
        },
        tenant: {
          id: 't_1',
          name: 'متجر فهرس',
          subdomain: credentials.subdomain || 'shop',
        },
        branch: { id: 'br_1', name: 'الفرع الرئيسي' },
        register: { id: 'reg_1', name: 'محطة الكاشير الرئيسية' },
      }
      return Promise.resolve(currentSession)
    },
    logout: () => {
      currentSession = null
      return Promise.resolve()
    },
    switchBranch: (branch) => {
      if (currentSession) {
        currentSession = { ...currentSession, branch }
      }
      return Promise.resolve()
    },
    switchRegister: (register) => {
      if (currentSession) {
        currentSession = { ...currentSession, register }
      }
      return Promise.resolve()
    },
  }

  const http: HttpPort = {
    request: <T = unknown>(endpoint: string): Promise<T> => {
      return Promise.resolve({ success: true, endpoint } as T)
    },
  }

  return {
    kind: 'noop',
    shell: {
      appInfo: () => Promise.resolve(info),
      openCustomerDisplay: () => {
        if (typeof window !== 'undefined') {
          window.open('#customer-display', 'fihrist_customer_display', 'width=1024,height=768')
        }
        return Promise.resolve(true)
      },
    },
    log: { write },
    runtime: {
      apiBaseUrl: () => Promise.resolve(options.apiBaseUrl ?? null),
      saveApiBaseUrl: () => Promise.resolve(true),
    },
    printer,
    updater,
    auth,
    http,
  }
}
