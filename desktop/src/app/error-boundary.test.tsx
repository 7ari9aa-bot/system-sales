import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

import { ErrorBoundary } from '@/app/error-boundary'
import { ApiError } from '@/platform/contract/envelope'

// React re-logs every error a boundary caught, by design. That noise is not what
// these tests are about, and a clean suite output is what makes the next real
// warning visible.
beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
})
afterEach(() => {
  vi.restoreAllMocks()
})

interface BoomProps {
  readonly code?: string
  readonly requestId?: string | null
  readonly renders?: () => void
}

function Boom({ code = 'internal', requestId = 'a1b2c3d4', renders }: BoomProps): ReactNode {
  renders?.()
  throw new ApiError({ code, message: 'فشل غير متوقع', retryable: false, requestId, status: 500 })
}

describe('<ErrorBoundary>', () => {
  it('leaves a healthy tree alone', () => {
    render(
      <ErrorBoundary onFatal={() => {}}>
        <p>inbox</p>
      </ErrorBoundary>,
    )

    expect(screen.getByText('inbox')).toBeTruthy()
  })

  it('names the product and surfaces the request id support needs', () => {
    render(
      <ErrorBoundary onFatal={() => {}}>
        <Boom />
      </ErrorBoundary>,
    )

    expect(screen.getByText(/Fihrist/)).toBeTruthy()
    expect(screen.getByRole('region').textContent).toContain('a1b2c3d4')
  })

  it('reports the machine code, not the message text', () => {
    render(
      <ErrorBoundary onFatal={() => {}}>
        <Boom code="version_conflict" />
      </ErrorBoundary>,
    )

    expect(screen.getByRole('region').dataset['code']).toBe('version_conflict')
  })

  it('hands the failure to the logger once, with the request id attached', () => {
    const onFatal = vi.fn()
    render(
      <ErrorBoundary onFatal={onFatal}>
        <Boom />
      </ErrorBoundary>,
    )

    expect(onFatal).toHaveBeenCalledTimes(1)
    expect(onFatal.mock.calls[0]?.[0]).toMatchObject({ code: 'internal', requestId: 'a1b2c3d4' })
  })

  /**
   * Restated after the first run: this test asserted exactly two renders, which
   * counted React's own behaviour rather than the product's — in DEV React
   * re-invokes a render that throws to build its warning, so every attempt costs
   * two calls. What must hold is that clicking retry runs the tree again and the
   * failure panel survives a second failure, which is what this now asserts.
   */
  it('gives a retry that re-runs the tree instead of stranding the user', () => {
    const renders = vi.fn()
    render(
      <ErrorBoundary onFatal={() => {}}>
        <Boom renders={renders} />
      </ErrorBoundary>,
    )

    const before = renders.mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: /إعادة المحاولة/ }))

    expect(renders.mock.calls.length).toBeGreaterThan(before)
    expect(screen.getByRole('region').dataset['code']).toBe('internal')
  })

  it('survives a thrown non-Error value', () => {
    const ThrowString = () => {
      throw 'nope'
    }
    render(
      <ErrorBoundary onFatal={() => {}}>
        <ThrowString />
      </ErrorBoundary>,
    )

    expect(screen.getByRole('region').dataset['code']).toBe('unknown')
  })
})
