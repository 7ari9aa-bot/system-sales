import { z } from 'zod'

import { call } from './invoke'
import type { AppInfo, LogPort, Platform, PrinterDevice, PrinterPort, RuntimePort, ShellPort, UpdateCheckResult, UpdaterPort } from '../port'
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

export function createTauriPlatform(): Platform {
  return { kind: 'tauri', shell, log, runtime, printer, updater }
}
