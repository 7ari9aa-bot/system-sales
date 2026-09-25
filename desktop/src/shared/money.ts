import { parseMoney } from '@/platform/contract/primitives'

export interface MoneyFormatOptions {
  readonly locale: string
  readonly currency: string
}

const NO_FRACTION_DIGITS = 0
const MAX_USEFUL_DIGITS = 20

/**
 * Format a decimal string for display without ever letting it become a number.
 *
 * `Intl.NumberFormat` cannot take a decimal string, and `Number(value)` is how
 * `9007199254740993.01` silently becomes `9007199254740992`. So the integer part
 * goes to Intl as a BigInt — which keeps the locale's grouping, separators and
 * digit shapes — and the fraction is re-attached digit by digit, exactly as the
 * server wrote it. Nothing here rounds and nothing here pads: the desktop shows
 * the precision the tenant's ledger carries.
 */
export function formatMoney(value: string, options: MoneyFormatOptions): string {
  const { negative, integer, fraction } = parseMoney(value)
  const currency = currencyFormatter(options.locale, options.currency)
  const digits = decimalFormatter(options.locale)
  const grouped = digits.format(BigInt(integer))
  const decimalSeparator = findSeparator(currency)

  const rendered = currency.formatToParts(-BigInt(integer === '0' ? '1' : integer))

  let out = ''
  let numberEmitted = false
  for (const part of rendered) {
    if (part.type === 'integer' || part.type === 'group') {
      // Intl splits a grouped number into alternating integer/group parts. The
      // grouping is already in `grouped`, so only the first part contributes.
      if (numberEmitted) continue
      numberEmitted = true
      out += grouped
      if (fraction) out += decimalSeparator + toLocaleDigits(fraction, digits)
      continue
    }
    if (part.type === 'minusSign') {
      out += negative ? part.value : ''
      continue
    }
    out += part.value
  }
  return out
}

function currencyFormatter(locale: string, currency: string): Intl.NumberFormat {
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    minimumFractionDigits: NO_FRACTION_DIGITS,
    maximumFractionDigits: MAX_USEFUL_DIGITS,
  })
}

function decimalFormatter(locale: string): Intl.NumberFormat {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: NO_FRACTION_DIGITS,
    maximumFractionDigits: NO_FRACTION_DIGITS,
  })
}

/**
 * A decimal separator has to come from a value that actually has a fraction.
 * 1.5 is exactly representable as a double, so this is the one place a Number is
 * allowed — it produces a character, never an amount.
 */
function findSeparator(formatter: Intl.NumberFormat): string {
  const decimal = formatter.formatToParts(1.5).find((part) => part.type === 'decimal')

  if (!decimal) throw new Error('locale has no decimal separator')

  return decimal.value
}

function toLocaleDigits(fraction: string, formatter: Intl.NumberFormat): string {
  let out = ''
  for (const char of fraction) out += formatter.format(BigInt(char))
  return out
}
