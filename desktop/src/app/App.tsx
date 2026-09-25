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
  }, [platform])

  return <BootScreen state={state} />
}
