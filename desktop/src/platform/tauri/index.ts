import { z } from 'zod'

import { call } from './invoke'
import type { AppInfo, LogPort, Platform, RuntimePort, ShellPort } from '../port'
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
  apiBaseUrl(): Promise<string | null> {
    if (!import.meta.env.DEV) return Promise.resolve(null)
    const configured: unknown = import.meta.env.FH_API_BASE_URL

    return Promise.resolve(typeof configured === 'string' && configured.trim() !== '' ? configured : null)
  },
}

export function createTauriPlatform(): Platform {
  return { kind: 'tauri', shell, log, runtime }
}
