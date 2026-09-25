import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

import { findViolations, scanTree } from '../check-platform-boundary.mjs'

// Vitest runs with the project root as cwd, and `new URL('./x', import.meta.url)`
// is rewritten by Vite's asset pipeline, so fixture paths are built from cwd.
const fixture = (rel) => join(process.cwd(), 'config', '__fixtures__', 'boundary', rel)

describe('findViolations', () => {
  it('accepts a UI file that only speaks through the platform interface', () => {
    const violations = findViolations({
      path: 'src/features/inbox/screen.tsx',
      code: `
        import { useQuery } from '@tanstack/react-query'
        import { platform } from '@/platform'
        export function Screen() {
          const { data } = useQuery({ queryKey: ['inbox'], queryFn: () => platform.http.get('/conversations') })
          return <p>{data?.length}</p>
        }
      `,
    })

    expect(violations).toEqual([])
  })

  it('rejects invoke() in the UI layer and names the file and line', () => {
    const violations = findViolations({
      path: 'src/features/orders/screen.tsx',
      code: `import { invoke } from '@tauri-apps/api/core'\nawait invoke('sync_now')\n`,
    })

    expect(violations.map((v) => v.rule)).toEqual(['no-invoke', 'no-tauri-import'])
    expect(violations[0]).toMatchObject({ line: 2, path: 'src/features/orders/screen.tsx' })
  })

  it('rejects a direct fetch() from a component', () => {
    const violations = findViolations({
      path: 'src/features/customers/picker.tsx',
      code: `const r = await fetch('https://api.internal.example/x')\nvoid r\n`,
    })

    expect(violations.some((v) => v.rule === 'no-fetch')).toBe(true)
  })

  it('rejects web storage, which is where a token would end up', () => {
    const violations = findViolations({
      path: 'src/state/session.ts',
      code: `localStorage.setItem('t', 'x')\nsessionStorage.getItem('t')\n`,
    })

    expect(violations.map((v) => v.rule)).toEqual(['no-web-storage', 'no-web-storage'])
  })

  it('rejects an EventSource, which cannot carry an Authorization header', () => {
    const violations = findViolations({
      path: 'src/platform/events.ts',
      code: `const es = new EventSource('/realtime')\nvoid es\n`,
    })

    expect(violations.some((v) => v.rule === 'no-event-source')).toBe(true)
  })

  it('rejects an `any` in the contract layer, where a generated client would park one', () => {
    const violations = findViolations({
      path: 'src/platform/contract/conversations.ts',
      code: `export type Message = { body: any }\n`,
    })

    expect(violations[0]?.rule).toBe('contract-no-any')
  })

  it('lets the adapter directory do the things nobody else may do', () => {
    const violations = findViolations({
      path: 'src/platform/tauri/http.adapter.ts',
      code: `import { invoke } from '@tauri-apps/api/core'\nawait invoke('http_request', { req })\n`,
    })

    expect(violations).toEqual([])
  })

  it('keeps comment text out of the verdict', () => {
    const violations = findViolations({
      path: 'src/app/boot.tsx',
      code: `// the UI never calls fetch() or invoke() — see docs/platform-boundary.md\nexport const x = 1\n`,
    })

    expect(violations).toEqual([])
  })
})

describe('scanTree', () => {
  it('passes the clean fixture tree', () => {
    expect(scanTree({ root: fixture('clean') })).toEqual([])
  })

  it('finds every violation in the dirty fixture tree, with paths', () => {
    const violations = scanTree({ root: fixture('dirty') })

    expect(violations.length).toBeGreaterThanOrEqual(4)
    expect(new Set(violations.map((v) => v.rule))).toEqual(
      new Set(['no-invoke', 'no-tauri-import', 'no-fetch', 'no-web-storage', 'contract-no-any']),
    )
  })

  it('refuses to scan nothing — an empty tree is a misconfiguration, not a pass', () => {
    expect(() => scanTree({ root: fixture('clean/nonexistent') })).toThrow(/no files/)
  })
})
