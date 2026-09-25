import { afterEach, describe, expect, it } from 'vitest'

import { createNoopPlatform, resolvePlatform } from '@/platform'
import type { LogRecord } from '@/shared/log'

/**
 * The whole point of the seam: the UI can be mounted, driven and asserted
 * without a Tauri runtime. If this file ever needs a Tauri global to pass, an
 * adapter leaked upward.
 */
describe('resolvePlatform', () => {
  afterEach(() => {
    const w = window as unknown as Record<string, unknown>
    delete w['__TAURI_INTERNALS__']
    delete w['__TAURI_METADATA__']
  })

  it('returns the in-memory platform in a plain browser, so vitest and `vite dev` work', async () => {
    expect((await resolvePlatform()).kind).toBe('noop')
  })

  it('exposes exactly the ports Phase 0 owns', async () => {
    const platform = await resolvePlatform()

    expect(Object.keys(platform).sort()).toEqual(['kind', 'log', 'runtime', 'shell'])
  })

  it('selects the Tauri platform when the runtime is present', async () => {
    const w = window as unknown as Record<string, unknown>
    w['__TAURI_INTERNALS__'] = { invoke: () => Promise.resolve({}) }

    expect((await resolvePlatform()).kind).toBe('tauri')
  })
})

describe('the noop log port', () => {
  it('delivers a record to its observer instead of dropping it', () => {
    const seen: LogRecord[] = []
    const platform = createNoopPlatform({ onLog: (record) => seen.push(record) })

    platform.log.write({
      level: 'info',
      message: 'booted',
      fields: { attempt: 1 },
      requestId: null,
      sink: 'test',
      ts: '2026-09-25T00:00:00.000Z',
    })

    expect(seen[0]?.message).toBe('booted')
  })

  it('answers "not configured" rather than inventing a host', async () => {
    const platform = createNoopPlatform({})

    expect(await platform.runtime.apiBaseUrl()).toBeNull()
  })

  it('reports the browser it is running in as the app info', async () => {
    const platform = createNoopPlatform({})

    expect(await platform.shell.appInfo()).toMatchObject({ productName: 'Fihrist', os: 'unknown' })
  })
})
