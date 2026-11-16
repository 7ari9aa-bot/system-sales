import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { runInNewContext } from 'node:vm'
import { describe, expect, it } from 'vitest'

/**
 * A real scanner sends an UPPERCASE letter or a symbol (`_ + #`) by holding Shift for that key.
 * Seen when the bridge was driven with real scanner key sequences: `Abc123` arrived as `abc123`
 * and `AB_123456` arrived as `-123456` (the letters before the Shift were thrown away), and the
 * backend matches a code exactly, so the sale looked up a different code or none. A human typing
 * is still told apart by SPEED, which is the gate that was always doing that job.
 */
const SOURCE = readFileSync(
  join(process.cwd(), 'src', 'platform', 'scanner', 'scan_bridge.js'),
  'utf8'
)

type Ev = { code: string; key?: string; shiftKey?: boolean; timeStamp: number }
type Out = { accepted: boolean; value?: string; rejected?: string }

function load() {
  const moduleShim = { exports: {} as Record<string, unknown> }
  runInNewContext(SOURCE, { module: moduleShim })
  return moduleShim.exports as {
    ScannerBuffer: new () => { push: (e: Ev) => Out }
  }
}

/** What a keyboard-wedge scanner emits for `text`: Shift down, the key (with shiftKey), Shift up. */
function scan(text: string, gap = 15): Out {
  const { ScannerBuffer } = load()
  const buffer = new ScannerBuffer()
  const physical: Record<string, [string, boolean]> = {
    '-': ['Minus', false],
    '_': ['Minus', true],
    '+': ['Equal', true],
    '#': ['Digit3', true],
    ' ': ['Space', false],
    '.': ['Period', false],
    '/': ['Slash', false],
  }
  let t = 1000
  for (const ch of text) {
    let code: string
    let shifted: boolean
    if (/[0-9]/.test(ch)) [code, shifted] = [`Digit${ch}`, false]
    else if (/[a-z]/.test(ch)) [code, shifted] = [`Key${ch.toUpperCase()}`, false]
    else if (/[A-Z]/.test(ch)) [code, shifted] = [`Key${ch}`, true]
    else [code, shifted] = physical[ch] ?? ['Unknown', false]
    if (shifted) {
      buffer.push({ code: 'ShiftLeft', key: 'Shift', shiftKey: true, timeStamp: t })
      t += gap
    }
    buffer.push({ code, key: ch, shiftKey: shifted, timeStamp: t })
    t += gap
  }
  return buffer.push({ code: 'Enter', key: 'Enter', timeStamp: t })
}

describe('a scanner that holds Shift for capitals and symbols', () => {
  it.each([
    ['an uppercase code', 'ABC123'],
    ['mixed case', 'Abc123'],
    ['an uppercase SKU with a dash', 'ABC-123'],
    ['a SKU with a shifted underscore', 'AB_123456'],
    ['a code with a plus', 'AB+123456'],
    ['a code with a hash', 'AB#123456'],
  ])('delivers %s exactly as printed', (_name, code) => {
    expect(scan(code)).toMatchObject({ accepted: true, value: code })
  })

  it('still delivers a plain digit barcode', () => {
    expect(scan('6221234567891')).toMatchObject({ accepted: true, value: '6221234567891' })
  })

  it('still refuses a human: the same keys at typing speed are not a scan', () => {
    expect(scan('ABC123', 150)).toMatchObject({ accepted: false })
  })

  it('a Shift pressed slowly in the middle of a burst still marks a human', () => {
    // Shift no longer spoils a burst by itself, so its timing must: a person who pauses before the
    // capital is typing, not scanning.
    const { ScannerBuffer } = load()
    const buffer = new ScannerBuffer()
    let t = 1000
    for (const code of ['Digit1', 'Digit2', 'Digit3', 'Digit4']) {
      buffer.push({ code, key: '1', shiftKey: false, timeStamp: t })
      t += 15
    }
    t += 300 // a human pause
    buffer.push({ code: 'ShiftLeft', key: 'Shift', shiftKey: true, timeStamp: t })
    t += 15
    for (const code of ['KeyA', 'KeyB', 'KeyC']) {
      buffer.push({ code, key: 'A', shiftKey: true, timeStamp: t })
      t += 15
    }
    // only the part after the pause is in the buffer: three characters, below the minimum
    expect(buffer.push({ code: 'Enter', key: 'Enter', timeStamp: t })).toEqual({
      accepted: false,
      rejected: 'too_short',
    })
  })

  it('a scanner that is slower on the Shift key is still one burst, because each step is fast', () => {
    // 50 ms to the Shift and 50 ms from it to the letter: each step is under the gap, but the digit
    // to the letter is 100 ms. The Shift must count as part of the burst or the letter would be
    // taken as the start of a new one and the code cut in two.
    const { ScannerBuffer } = load()
    const buffer = new ScannerBuffer()
    let t = 1000
    for (const code of ['Digit1', 'Digit2', 'Digit3', 'Digit4', 'Digit5', 'Digit6']) {
      buffer.push({ code, key: '1', shiftKey: false, timeStamp: t })
      t += 15
    }
    buffer.push({ code: 'ShiftLeft', key: 'Shift', shiftKey: true, timeStamp: t + 50 })
    buffer.push({ code: 'KeyA', key: 'A', shiftKey: true, timeStamp: t + 100 })
    expect(buffer.push({ code: 'Enter', key: 'Enter', timeStamp: t + 115 })).toMatchObject({
      accepted: true,
      value: '123456A',
    })
  })

  it('an unshifted Equal or Space is not a barcode character', () => {
    const { ScannerBuffer } = load()
    for (const code of ['Equal', 'Space']) {
      const buffer = new ScannerBuffer()
      let t = 1000
      for (const c of ['Digit1', 'Digit2', 'Digit3', 'Digit4', 'Digit5', 'Digit6', code]) {
        buffer.push({ code: c, key: 'x', shiftKey: false, timeStamp: t })
        t += 15
      }
      // the key is not a barcode character, so it ends the burst: nothing is delivered
      expect(buffer.push({ code: 'Enter', key: 'Enter', timeStamp: t })).toMatchObject({
        accepted: false,
      })
    }
  })

  it('Shift alone, with nothing typed, delivers nothing', () => {
    const { ScannerBuffer } = load()
    const buffer = new ScannerBuffer()
    buffer.push({ code: 'ShiftLeft', key: 'Shift', shiftKey: true, timeStamp: 1000 })
    expect(buffer.push({ code: 'Enter', key: 'Enter', timeStamp: 1010 })).toEqual({
      accepted: false,
      rejected: 'too_short',
    })
  })

  it('a layout-independent letter is still decoded from the physical key', () => {
    // Arabic layout: event.key would be an Arabic letter, event.code is still KeyD
    const { ScannerBuffer } = load()
    const buffer = new ScannerBuffer()
    let t = 1000
    for (const code of ['KeyD', 'Digit2', 'Digit3', 'Digit4', 'Digit5', 'Digit6']) {
      buffer.push({ code, key: 'ي', shiftKey: false, timeStamp: t })
      t += 15
    }
    expect(buffer.push({ code: 'Enter', key: 'Enter', timeStamp: t })).toMatchObject({
      accepted: true,
      value: 'd23456',
    })
  })
})
