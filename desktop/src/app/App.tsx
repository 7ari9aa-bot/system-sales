import { useEffect, useState, type FC } from 'react'

import { BootScreen } from '@/app/boot-screen'
import type { BootState } from '@/app/boot-state'
import { AppShell } from '@/app/shell/AppShell'
import { LoginView } from '@/features/auth/LoginView'
import { CustomerDisplayView } from '@/features/cashier/CustomerDisplayView'
import type { AuthSession, Platform } from '@/platform'
import { parseRuntimeConfig } from '@/platform/runtime'

export const App: FC<{ readonly platform: Platform }> = ({ platform }) => {
  const isCustomerDisplay = typeof window !== 'undefined' && window.location.hash === '#customer-display'

  const [state, setState] = useState<BootState>({ status: 'checking' })
  const [refreshKey, setRefreshKey] = useState(0)
  const [session, setSession] = useState<AuthSession | null>(null)
  const [sessionChecking, setSessionChecking] = useState(true)
  const [forceConfigure, setForceConfigure] = useState(false)

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

  // Check auth session when server configuration is valid
  useEffect(() => {
    if (state.status !== 'ok') return

    let alive = true
    void platform.auth
      .getSession()
      .then((sess) => {
        if (alive) {
          setSession(sess)
          setSessionChecking(false)
        }
      })
      .catch(() => {
        if (alive) {
          setSession(null)
          setSessionChecking(false)
        }
      })

    return () => {
      alive = false
    }
  }, [platform, state.status, refreshKey])

  const handleSave = (url: string): void => {
    if (platform.runtime.saveApiBaseUrl) {
      void platform.runtime.saveApiBaseUrl(url).then((ok) => {
        if (ok) {
          setRefreshKey((k) => k + 1)
          setForceConfigure(false)
        }
      })
    }
  }

  // If loaded as customer display secondary window, directly render customer display
  if (isCustomerDisplay) {
    return <CustomerDisplayView />
  }

  // If configuration is valid and server resolved
  if (state.status === 'ok' && !forceConfigure) {
    if (sessionChecking) {
      return (
        <div className="boot" dir="rtl">
          <div className="boot__card" role="status">
            <h1 className="boot__title">فهرس FIHRIST</h1>
            <p className="boot__lead">جارٍ استعادة الجلسة والتحقق من محطة التشغيل...</p>
          </div>
        </div>
      )
    }

    if (!session) {
      return (
        <LoginView
          platform={platform}
          onAuthenticated={(sess) => setSession(sess)}
          onConfigureServer={() => setForceConfigure(true)}
        />
      )
    }

    return (
      <AppShell
        platform={platform}
        session={session}
        onLogout={() => {
          void platform.auth.logout().then(() => setSession(null))
        }}
        apiBaseUrl={state.apiBaseUrl}
        onSaveUrl={handleSave}
      />
    )
  }

  // Otherwise, show boot configuration screen
  return (
    <BootScreen
      state={state}
      onSave={
        platform.runtime.saveApiBaseUrl
          ? (url) => {
              handleSave(url)
            }
          : undefined
      }
    />
  )
}
