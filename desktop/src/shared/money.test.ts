import { describe, expect, it } from 'vitest'

import { formatMoney } from '@/shared/money'

/**
 * Money is a string on the wire and must stay one. Intl cannot format a decimal
 * string, so the implementation formats the integer part from a BigInt and
 * re-attaches the fraction it was given — rounding is a product defect here.
 */
const arabicIndicToAscii = (input: string): string =>
  input
    .replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660))
    .replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06f0))
    // U+066C is the Arabic thousands separator, U+066B the decimal sign. Both
    // appear or not depending on the locale's CLDR symbols, so the helper
    // normalises either shape into the ASCII one the assertion reads.
    .replace(/[،٬]/g, ',')
    .replace(/[٫.]/g, '.')
    .replace(/[\u061c\u200f\u200e\s]/g, '')

describe('formatMoney', () => {
  it('groups and prefixes in en-US', () => {
    expect(formatMoney('1234567.89', { locale: 'en-US', currency: 'USD' })).toBe('$1,234,567.89')
  })

  it('renders Arabic-Indic digits for a locale whose numbering system is arab', () => {
    const out = formatMoney('1234567.89', { locale: 'ar-EG', currency: 'EGP' })

    expect(out).not.toMatch(/[0-9]/)
    expect(arabicIndicToAscii(out)).toContain('1,234,567.89')
  })

  it('renders Latin digits when the locale asks for them — the digit shape is the locale’s, not ours', () => {
    const out = formatMoney('1234567.89', { locale: 'ar-EG-u-nu-latn', currency: 'EGP' })

    expect(out).toContain('1,234,567.89')
  })

  it('keeps a value a double cannot hold', () => {
    expect(formatMoney('9007199254740993.01', { locale: 'en-US', currency: 'USD' })).toBe(
      '$9,007,199,254,740,993.01',
    )
  })

  it('shows the precision the server sent — never rounds, never pads', () => {
    const opts = { locale: 'en-US', currency: 'USD' } as const

    expect(formatMoney('10.500', opts)).toBe('$10.500')
    expect(formatMoney('700', opts)).toBe('$700')
    expect(formatMoney('0', opts)).toBe('$0')
  })

  it('places the minus sign the way the locale does', () => {
    expect(formatMoney('-1234.5', { locale: 'en-US', currency: 'USD' })).toBe('-$1,234.5')
  })

  it('refuses a value that is not a decimal string', () => {
    expect(() => formatMoney('1.2.3', { locale: 'en-US', currency: 'USD' })).toThrow(/invalid money/i)
  })

  it('refuses a currency it cannot format rather than printing a bare number', () => {
    expect(() => formatMoney('1.00', { locale: 'en-US', currency: 'NOT_A_CODE' })).toThrow()
  })
})
