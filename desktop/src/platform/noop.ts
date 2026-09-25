import type { LogRecord } from '@/shared/log'

import type { AppInfo, NoopPlatformOptions, Platform } from './port'

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
    // Deliberately not sniffed from the user agent: a webview UA is not the OS
    // the shell would report, and pretending otherwise is how platform-specific
    // bugs get "tested" in the wrong place.
    os: 'unknown',
  }

  const write = (record: LogRecord): void => {
    options.onLog?.(record)
  }

  return {
    kind: 'noop',
    // Resolved promises rather than `async` methods: the ports are asynchronous
    // because the real adapters are, and an in-memory answer has nothing to wait
    // for — `await` here would be decoration.
    shell: { appInfo: () => Promise.resolve(info) },
    log: { write },
    runtime: { apiBaseUrl: () => Promise.resolve(options.apiBaseUrl ?? null) },
  }
}
