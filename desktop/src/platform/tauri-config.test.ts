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
    expect(conf['app']['windows'][0]['title']).toBe('Fihrist')
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

  it('declares only the main window in Phase 0', () => {
    expect(conf['app']['windows']).toHaveLength(1)
    expect(conf['app']['windows'][0]['label']).toBe('main')
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
