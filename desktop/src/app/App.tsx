import { useEffect, useState } from 'react'

import { BootScreen } from '@/app/boot-screen'
import type { BootState } from '@/app/boot-state'
import type { Platform } from '@/platform'
import { parseRuntimeConfig } from '@/platform/runtime'

/**
 * Phase 0 ends here on purpose: the shell resolves its one piece of runtime
 * configuration and reports it. Login, inbox and everything after it belong to
 * Phase 1 and Phase 4, and nothing here pre-decides their shape.
 */
export function App({ platform }: { readonly platform: Platform }) {
  const [state, setState] = useState<BootState>({ status: 'checking' })
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
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
  }, [platform, refreshKey])

  const handleSave = (url: string): void => {
    if (platform.runtime.saveApiBaseUrl) {
      void platform.runtime.saveApiBaseUrl(url).then((ok) => {
        if (ok) {
          setRefreshKey((k) => k + 1)
        }
      })
    }
  }

  return <BootScreen state={state} onSave={platform.runtime.saveApiBaseUrl ? handleSave : undefined} />
}
