import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * These are not documentation tests. They are the only thing standing between a
 * copied-in plugin example and an app that ships `shell:allow-execute`, an LTR
 * window title, or the previous product's name.
 */
const root = process.cwd()
const conf = JSON.parse(readFileSync(join(root, 'src-tauri', 'tauri.conf.json'), 'utf8')) as Record<string, any>
const capabilityDir = join(root, 'src-tauri', 'capabilities')

const WINDOW_LABELS = ['main', 'auth', 'settings', 'utility'] as const

describe('tauri.conf.json', () => {
  it('carries the Fihrist identity, not the imported architecture doc’s', () => {
    expect(conf['productName']).toBe('Fihrist')
    expect(conf['identifier']).toBe('com.fihrist.desktop')
    // The window is created in Rust (wrap mode needs a dynamic URL and an
    // injected initialization script), so the identity now lives in lib.rs.
    const lib = readFileSync(join(root, 'src-tauri', 'src', 'lib.rs'), 'utf8')
    expect(lib).toContain('.title("Fihrist")')
    expect(lib).toContain('"main"')
  })

  it('has no trace of the old product name', () => {
    const raw = readFileSync(join(root, 'src-tauri', 'tauri.conf.json'), 'utf8').toLowerCase()

    for (const stale of ['lead engine', 'lead-engine', 'leadengine']) {
      expect(raw, stale).not.toContain(stale)
    }
  })

  it('ships a CSP that defaults to self and never allows a remote script', () => {
    const csp = String(conf['app']['security']['csp'])

    expect(csp).toContain("default-src 'self'")
    expect(csp).not.toMatch(/script-src[^;]*\*/)
    expect(csp).not.toContain('unsafe-eval')
  })

  it('keeps the bridge off the global namespace', () => {
    expect(conf['app']['withGlobalTauri'] ?? false).toBe(false)
  })

  it('points at the static build output and the strict dev port', () => {
    expect(conf['build']['frontendDist']).toBe('../dist')
    expect(conf['build']['devUrl']).toBe('http://127.0.0.1:5183')
  })

  it('declares NO static window — wrap mode builds `main` in setup with a runtime URL', () => {
    // A static window entry cannot carry the resolved web-app URL or the scan
    // bridge injection; the only correct count here is zero.
    expect(conf['app']['windows']).toHaveLength(0)
    const lib = readFileSync(join(root, 'src-tauri', 'src', 'lib.rs'), 'utf8')
    expect(lib).toContain('WebviewWindowBuilder::new')
    expect(lib).toContain('initialization_script')
  })

  it('names icons that exist on disk', () => {
    for (const icon of conf['bundle']['icon'] as string[]) {
      expect(existsSync(join(root, 'src-tauri', icon)), icon).toBe(true)
    }
  })
})

describe('capabilities', () => {
  const files = readdirSync(capabilityDir).filter((f) => f.endsWith('.json'))

  it('is one file per window, and no window is unaccounted for', () => {
    expect(files.sort()).toEqual([...WINDOW_LABELS].map((label) => `${label}.json`).sort())
  })

  it('references only windows the app can create', () => {
    for (const file of files) {
      const cap = JSON.parse(readFileSync(join(capabilityDir, file), 'utf8')) as Record<string, any>
      for (const window of cap['windows'] as string[]) {
        expect(WINDOW_LABELS, `${file} → ${window}`).toContain(window)
      }
    }
  })

  it('grants core permissions only: deny by default is not a slogan', () => {
    for (const file of files) {
      const cap = JSON.parse(readFileSync(join(capabilityDir, file), 'utf8')) as Record<string, any>

      for (const permission of cap['permissions'] as string[]) {
        expect(permission, `${file} → ${permission}`).toMatch(/^core:/)
      }
    }
  })

  it('carries no capability that could run a program, read a disk, or open a socket', () => {
    const banned = ['shell', 'fs:', 'http:', 'updater', 'process:', 'notification', 'global-shortcut', 'allow-execute', 'sidecar']

    for (const file of files) {
      const raw = readFileSync(join(capabilityDir, file), 'utf8')

      for (const word of banned) {
        expect(raw.toLowerCase(), `${file} → ${word}`).not.toContain(word)
      }
    }
  })

  it('says what each capability is for', () => {
    for (const file of files) {
      const cap = JSON.parse(readFileSync(join(capabilityDir, file), 'utf8')) as Record<string, any>

      expect(cap['identifier']).toBe(file.replace(/\.json$/, ''))
      expect(String(cap['description']).length).toBeGreaterThan(20)
    }
  })
})
