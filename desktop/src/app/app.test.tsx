import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { App } from '@/app/App'
import { ErrorBoundary } from '@/app/error-boundary'
import { createNoopPlatform } from '@/platform'
import type { Platform } from '@/platform'

function platformWithBaseUrl(apiBaseUrl: string | null): Platform {
  return createNoopPlatform({ apiBaseUrl })
}

function renderApp(platform: Platform) {
  return render(
    <ErrorBoundary onFatal={vi.fn()}>
      <App platform={platform} />
    </ErrorBoundary>,
  )
}

/**
 * Phase 0 ships no screens, but it ships the states every later screen inherits:
 * loading, configuration-required, and ready. A feature that arrives in Phase 4
 * has to find these already handled, not invent them per screen.
 */
describe('<App> boot states', () => {
  it('waits without guessing while the address is unresolved', () => {
    const never = new Promise<string | null>(() => {})
    const pending: Platform = { ...createNoopPlatform({}), runtime: { apiBaseUrl: () => never } }

    renderApp(pending)

    expect(screen.getByRole('status').textContent).toContain('جارٍ تجهيز')
  })

  it('says what is missing instead of pointing at a host nobody chose', async () => {
    renderApp(platformWithBaseUrl(null))

    expect(await screen.findByText(/لم يُضبط عنوان الخادم/)).toBeTruthy()
    expect(screen.getByText('Fihrist')).toBeTruthy()
  })

  it('refuses an address that would send a bearer over plain http', async () => {
    renderApp(platformWithBaseUrl('http://api.fihrist.app'))

    expect(await screen.findByText(/https/)).toBeTruthy()
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('reports the resolved address once it validates', async () => {
    renderApp(platformWithBaseUrl('https://api.fihrist.app/api/v1/'))

    expect(await screen.findByText(/api\.fihrist\.app\/api\/v1$/)).toBeTruthy()
  })
})
