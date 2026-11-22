import { useEffect, useState, type FC } from 'react'

import { BootScreen } from '@/app/boot-screen'
import type { BootState } from '@/app/boot-state'
import { AppShell } from '@/app/shell/AppShell'
import { CustomerDisplayView } from '@/features/cashier/CustomerDisplayView'
import type { Platform } from '@/platform'
import { parseRuntimeConfig } from '@/platform/runtime'

export const App: FC<{ readonly platform: Platform }> = ({ platform }) => {
  const isCustomerDisplay = typeof window !== 'undefined' && window.location.hash === '#customer-display'

  const [state, setState] = useState<BootState>({ status: 'checking' })
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    if (isCustomerDisplay) return

    let alive = true

    void platform.runtime
      .apiBaseUrl()
      .then((raw) => {
        if (!alive) return
        const parsed = parseRuntimeConfig(raw)

        setState(parsed.ok ? { status: 'ok', apiBaseUrl: parsed.apiBaseUrl } : { status: parsed.reason })
      })
      .catch(() => {
        if (alive) setState({ status: 'invalid' })
      })

    return () => {
      alive = false
    }
  }, [platform, refreshKey, isCustomerDisplay])

  const handleSave = (url: string): void => {
    if (platform.runtime.saveApiBaseUrl) {
      void platform.runtime.saveApiBaseUrl(url).then((ok) => {
        if (ok) {
          setRefreshKey((k) => k + 1)
        }
      })
    }
  }

  // If loaded as customer display secondary window, directly render customer display
  if (isCustomerDisplay) {
    return <CustomerDisplayView />
  }

  // If configuration is valid and server resolved, render the native desktop workstation shell!
  if (state.status === 'ok') {
    return <AppShell platform={platform} apiBaseUrl={state.apiBaseUrl} onSaveUrl={handleSave} />
  }

  // Otherwise, show boot configuration screen
  return <BootScreen state={state} onSave={platform.runtime.saveApiBaseUrl ? handleSave : undefined} />
}
