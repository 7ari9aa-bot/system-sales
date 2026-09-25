import { describe, expect, it } from 'vitest'

import { findHardcodedHosts } from '../check-no-hardcoded-host.mjs'

/**
 * The base URL is runtime configuration. The failure this gate prevents is a
 * `.env` that was present at build time getting inlined into the shipped bundle,
 * which turns a configurable client into a client pointed at one host forever.
 */
describe('findHardcodedHosts', () => {
  it('accepts a bundle whose only URLs are specification namespaces', () => {
    const violations = findHardcodedHosts({
      path: 'dist/assets/index.js',
      code: `const NS='http://www.w3.org/2000/svg';console.error('see https://react.dev/errors/418')`,
    })

    expect(violations).toEqual([])
  })

  it('rejects a host that came from a build-time environment file', () => {
    const violations = findHardcodedHosts({
      path: 'dist/assets/index.js',
      code: `const base="https://api.staging.internal.example/v1"`,
    })

    expect(violations).toHaveLength(1)
    expect(violations[0]).toMatchObject({ rule: 'no-hardcoded-host', line: 1 })
    expect(violations[0].message).toContain('https://api.staging.internal.example')
  })

  it('rejects an http origin too, because a loopback default is not a product default', () => {
    const violations = findHardcodedHosts({
      path: 'dist/assets/boot.js',
      code: `fetch('http://localhost:8000/api/v1')`,
    })

    expect(violations[0]?.rule).toBe('no-hardcoded-host')
  })
})
