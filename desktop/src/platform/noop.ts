import type { LogRecord } from '@/shared/log'

import type { AppInfo, NoopPlatformOptions, Platform, PrinterPort, UpdaterPort } from './port'

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

  return {
    kind: 'noop',
    shell: { appInfo: () => Promise.resolve(info) },
    log: { write },
    runtime: {
      apiBaseUrl: () => Promise.resolve(options.apiBaseUrl ?? null),
      saveApiBaseUrl: () => Promise.resolve(true),
    },
    printer,
    updater,
  }
}
