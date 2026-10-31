import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { runInNewContext } from 'node:vm'
import { describe, expect, it } from 'vitest'

/**
 * The bridge source is exercised AS SHIPPED: the same bytes `include_str!`
 * embeds into the webview are evaluated here. `runInNewContext` captures the
 * pure pieces through the file's CommonJS branch; integration tests drive the
 * auto-installed listener against the real jsdom window. This is the contract
 * that keeps the injected script and the tested logic from drifting apart.
 */
const SOURCE = readFileSync(
  join(process.cwd(), 'src', 'platform', 'scanner', 'scan_bridge.js'),
  'utf8'
)

function load() {
  const captured: Record<string, unknown> = {}
  const moduleShim = { exports: captured }
  runInNewContext(SOURCE, { module: moduleShim })
  return moduleShim.exports as {
    SCAN_EVENT_NAME: string
    decodeEventCode: (event: { code?: string }) => string | null
    isEditableTarget: (event: { target?: unknown }) => boolean
    ScannerBuffer: new (options?: { maxGapMs?: number; minLength?: number; maxLength?: number }) => {
      push: (event: { code?: string; timeStamp?: number }) => {
        accepted: boolean
        value?: string
        durationMs?: number
        rejected?: string
      }
      reset: () => void
    }
    install: (targetWindow: Window) => boolean
  }
}

function key(code: string, timeStamp: number) {
  return { code, timeStamp }
}

type ScannerBufferInstance = InstanceType<ReturnType<typeof load>['ScannerBuffer']>

/** A scanner burst: 13 digits, ~20 ms apart, Enter terminator. */
function ean13Burst(buffer: ScannerBufferInstance) {
  const outcomes = []
  let t = 100
  for (let i = 0; i < 13; i += 1) {
    outcomes.push(buffer.push(key(`Digit${i % 10}`, t)))
    t += 20
  }
  outcomes.push(buffer.push(key('Enter', t + 5)))
  return outcomes
}

describe('decodeEventCode', () => {
  const { decodeEventCode } = load()

  it('decodes physical keys, layout-immune — the Arabic-layout guarantee', () => {
    expect(decodeEventCode({ code: 'KeyD' })).toBe('d')
    expect(decodeEventCode({ code: 'KeyT' })).toBe('t')
    expect(decodeEventCode({ code: 'Digit5' })).toBe('5')
    expect(decodeEventCode({ code: 'Numpad5' })).toBe('5')
    expect(decodeEventCode({ code: 'Minus' })).toBe('-')
  })

  it('returns null for anything that is not a barcode character', () => {
    for (const code of ['ShiftLeft', 'ControlLeft', 'Backspace', 'NumpadEnter', 'F2', 'Tab', 'Escape', 'Space', '']) {
      expect(decodeEventCode({ code })).toBeNull()
    }
    expect(decodeEventCode({})).toBeNull()
    expect(decodeEventCode(null as unknown as { code?: string })).toBeNull()
  })
})

describe('ScannerBuffer', () => {
  const { ScannerBuffer } = load()

  it('accepts a fast burst of barcode-charset characters ended by Enter', () => {
    const buffer = new ScannerBuffer()
    const outcomes = ean13Burst(buffer)
    const final = outcomes[outcomes.length - 1]!
    expect(final.accepted).toBe(true)
    expect(final.value).toBe('0123456789012')
    expect(final.durationMs).toBeGreaterThan(0)
  })

  it('accepts NumpadEnter as a terminator and mixed alphanumerics', () => {
    const buffer = new ScannerBuffer()
    const codes = ['KeyA', 'KeyB', 'Digit1', 'Minus', 'KeyC', 'Digit2']
    let t = 100
    for (const code of codes) {
      buffer.push(key(code, t))
      t += 20
    }
    const final = buffer.push(key('NumpadEnter', t + 5))
    expect(final.accepted).toBe(true)
    expect(final.value).toBe('ab1-c2')
  })

  it('rejects a burst broken by a human-paced gap — the buffer resets', () => {
    const buffer = new ScannerBuffer()
    let t = 100
    for (let i = 0; i < 8; i += 1) {
      buffer.push(key('Digit7', t))
      t += 20
    }
    t += 500 // a human paused; a scanner never would
    buffer.push(key('Digit7', t))
    const final = buffer.push(key('Enter', t + 5))
    expect(final).toEqual({ accepted: false, rejected: 'too_short' })
  })

  it('rejects on the first non-barcode key — one human key spoils the burst', () => {
    const buffer = new ScannerBuffer()
    let t = 100
    for (let i = 0; i < 8; i += 1) {
      buffer.push(key('Digit3', t))
      t += 20
    }
    buffer.push(key('ShiftLeft', t)) // human noise
    const final = buffer.push(key('Enter', t + 5))
    expect(final).toEqual({ accepted: false, rejected: 'too_short' })
  })

  it('accepts six-letter codes (length is the only gate a letter burst can trip)', () => {
    // decodeEventCode can never emit a forbidden character, so the charset
    // reject is unreachable through the public API — length is what a letter
    // burst is actually tested against.
    const buffer = new ScannerBuffer()
    let t = 100
    for (const code of ['KeyA', 'KeyB', 'KeyC', 'KeyD', 'KeyE', 'KeyF']) {
      buffer.push(key(code, t))
      t += 20
    }
    const final = buffer.push(key('Enter', t + 5))
    expect(final.accepted).toBe(true)
    expect(final.value).toBe('abcdef')
  })
})

describe('install (integration, real jsdom window)', () => {
  const { install, SCAN_EVENT_NAME } = load()

  it('installs once, refuses a second install, and unsets nothing on reload of the page object', () => {
    expect(install(window)).toBe(true)
    expect(install(window)).toBe(false)
    expect((window as unknown as { __FIHRIST_SCAN_BRIDGE_INSTALLED?: boolean }).__FIHRIST_SCAN_BRIDGE_INSTALLED).toBe(
      true
    )
  })

  it('captures a scan while focus is NOT editable and dispatches fihrist:scan', () => {
    install(window)
    const received: Array<{ value: string; durationMs: number }> = []
    window.addEventListener(SCAN_EVENT_NAME, (event) => {
      received.push((event as CustomEvent<{ value: string; durationMs: number }>).detail)
    })

    for (let i = 0; i < 13; i += 1) {
      document.body.dispatchEvent(new KeyboardEvent('keydown', { code: `Digit${i % 10}`, bubbles: true }))
    }
    const enter = new KeyboardEvent('keydown', { code: 'Enter', bubbles: true, cancelable: true })
    document.body.dispatchEvent(enter)

    expect(received).toHaveLength(1)
    expect(received[0]!.value).toBe('0123456789012')
    expect(enter.defaultPrevented).toBe(true)
  })

  it('stays silent when focus IS editable — no event, no preventDefault (double-add guard)', () => {
    install(window)
    const received: unknown[] = []
    window.addEventListener(SCAN_EVENT_NAME, (event) => {
      received.push((event as CustomEvent).detail)
    })
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()

    for (let i = 0; i < 13; i += 1) {
      input.dispatchEvent(new KeyboardEvent('keydown', { code: `Digit${i % 10}`, bubbles: true }))
    }
    const enter = new KeyboardEvent('keydown', { code: 'Enter', bubbles: true, cancelable: true })
    input.dispatchEvent(enter)

    expect(received).toHaveLength(0)
    expect(enter.defaultPrevented).toBe(false)
  })
})
