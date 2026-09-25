import { describe, expect, it } from 'vitest'

import { MoneyError, moneySchema, parseMoney } from '@/platform/contract/primitives'

describe('money on the wire', () => {
  it('accepts a decimal string, because Decimal columns arrive as strings', () => {
    expect(moneySchema.parse('1234.56')).toBe('1234.56')
  })

  it('rejects a number even when it is exact — a float on the wire is a defect', () => {
    expect(moneySchema.safeParse(1234.56).success).toBe(false)
  })

  it('rejects a money value that came through a float already (1.2345678901234567e21)', () => {
    expect(moneySchema.safeParse('1.2345678901234567e+21').success).toBe(false)
  })

  it('rejects malformed decimals instead of cleaning them up', () => {
    for (const raw of ['1.2.3', '.5', '5.', '-', '', '1 000.5', '١٢٣']) {
      expect(moneySchema.safeParse(raw).success, raw).toBe(false)
    }
  })

  it('keeps every digit of a value that a double cannot hold', () => {
    const parts = parseMoney('9007199254740993.01')

    expect(parts).toEqual({ negative: false, integer: '9007199254740993', fraction: '01' })
  })

  it('keeps the sign and the trailing precision the server sent', () => {
    expect(parseMoney('-10.500')).toEqual({ negative: true, integer: '10', fraction: '500' })
  })

  it('normalises a whole amount to an empty fraction, not a fake .0', () => {
    expect(parseMoney('700')).toEqual({ negative: false, integer: '700', fraction: '' })
  })

  it('throws a typed error for a value that slipped past validation', () => {
    expect(() => parseMoney('1e9')).toThrowError(MoneyError)
  })
})

describe('decimal equality without arithmetic', () => {
  it('treats 10.5 and 10.50 as the same amount', async () => {
    const { moneyEquals } = await import('@/platform/contract/primitives')
    expect(moneyEquals('10.5', '10.50')).toBe(true)
  })

  it('does not treat a rounded cent as equal', async () => {
    const { moneyEquals } = await import('@/platform/contract/primitives')
    expect(moneyEquals('10.005', '10.00')).toBe(false)
  })
})
