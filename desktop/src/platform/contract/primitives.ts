import { z } from 'zod'

/**
 * Decimal columns leave this API as strings (docs §3.1 of the desktop review).
 * A client that parses them to a double re-creates the rounding bug the backend
 * spent a wave deleting, so money is validated as a string and stays one until
 * the presentation edge formats it.
 */
const DECIMAL_STRING = /^-?\d+(?:\.\d+)?$/

export const moneySchema = z
  .string()
  .regex(DECIMAL_STRING, { message: 'money must be a decimal string, never a number' })

export const uuidSchema = z.string().uuid()

export const requestIdSchema = z.string().min(1).max(64)

export class MoneyError extends Error {
  override readonly name = 'MoneyError'

  constructor(readonly raw: string) {
    super(`invalid money value: ${JSON.stringify(raw)}`)
  }
}

export interface MoneyParts {
  readonly negative: boolean
  readonly integer: string
  readonly fraction: string
}

export function parseMoney(raw: string): MoneyParts {
  if (!DECIMAL_STRING.test(raw)) throw new MoneyError(raw)

  const negative = raw.startsWith('-')
  const unsigned = negative ? raw.slice(1) : raw
  const [integer = '0', fraction = ''] = unsigned.split('.')

  return { negative, integer: stripLeadingZeros(integer), fraction }
}

/**
 * Compare two decimal strings digit by digit. Any arithmetic here would have to
 * go through a number, and that is exactly what this module exists to prevent.
 */
export function moneyEquals(a: string, b: string): boolean {
  const left = normalise(a)
  const right = normalise(b)

  return left === right
}

function normalise(raw: string): string {
  const { negative, integer, fraction } = parseMoney(raw)
  const trimmed = fraction.replace(/0+$/, '')
  const sign = integer === '0' && trimmed === '' ? '' : negative ? '-' : '+'

  return `${sign}${integer}.${trimmed}`
}

function stripLeadingZeros(digits: string): string {
  return digits.replace(/^0+(?=\d)/, '')
}
