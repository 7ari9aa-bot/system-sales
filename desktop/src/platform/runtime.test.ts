import { describe, expect, it } from 'vitest'

import { parseRuntimeConfig } from '@/platform/runtime'

/**
 * §5 of the mission: the API base URL is a runtime value, `.env.example` ships
 * empty, and boot validates rather than guessing a host.
 */
describe('parseRuntimeConfig', () => {
  it('reports a missing value as a configuration state, not a crash', () => {
    for (const raw of [undefined, null, '', '   ']) {
      expect(parseRuntimeConfig(raw)).toEqual({ ok: false, reason: 'missing' })
    }
  })

  it('refuses a string that is not an absolute http(s) URL', () => {
    for (const raw of ['api.fihrist.app', '/api/v1', 'ftp://api.fihrist.app', 'javascript:alert(1)', 'https://']) {
      expect(parseRuntimeConfig(raw)).toEqual({ ok: false, reason: 'invalid' })
    }
  })

  /**
   * Corrected expectation. This test first asserted that `https:/api.fihrist.app`
   * was invalid; it is not — WHATWG (and therefore `new URL`, and therefore every
   * browser) resolves a special scheme written without the authority marker to the
   * same origin, so rejecting it would diverge from the platform without buying
   * anything. The assertion is now the normalisation itself.
   */
  it('normalises the special-scheme form a browser would also accept', () => {
    expect(parseRuntimeConfig('https:/api.fihrist.app')).toEqual({
      ok: true,
      apiBaseUrl: 'https://api.fihrist.app',
    })
  })

  it('refuses credentials in the URL — a bearer never rides in a host', () => {
    expect(parseRuntimeConfig('https://user:***@api.fihrist.app')).toEqual({ ok: false, reason: 'invalid' })
  })

  it('refuses a query string, which is where a token would leak', () => {
    expect(parseRuntimeConfig('https://api.fihrist.app/?token=***')).toEqual({
      ok: false,
      reason: 'invalid',
    })
  })

  it('requires https in the real world', () => {
    expect(parseRuntimeConfig('http://api.fihrist.app')).toEqual({ ok: false, reason: 'insecure' })
  })

  it('allows plain http against loopback, because local development is a supported state', () => {
    expect(parseRuntimeConfig('http://127.0.0.1:8000')).toEqual({ ok: true, apiBaseUrl: 'http://127.0.0.1:8000' })
    expect(parseRuntimeConfig('http://localhost:8000/api/v1')).toEqual({
      ok: true,
      apiBaseUrl: 'http://localhost:8000/api/v1',
    })
  })

  it('normalises the value: trimmed, no trailing slash, no fragment', () => {
    expect(parseRuntimeConfig('  https://api.fihrist.app/api/v1/  ')).toEqual({
      ok: true,
      apiBaseUrl: 'https://api.fihrist.app/api/v1',
    })
  })

  it('keeps a non-root base path intact', () => {
    expect(parseRuntimeConfig('https://gateway.internal/fh')).toEqual({
      ok: true,
      apiBaseUrl: 'https://gateway.internal/fh',
    })
  })
})
