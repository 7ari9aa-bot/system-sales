import { describe, expect, it } from 'vitest'

import { LOCALES, MESSAGES, directionOf, message } from '@/shared/i18n'

/**
 * The desktop is Arabic-first. A key that only exists in English is how an
 * LTR-only product sneaks in one string at a time, so the catalog is checked
 * for completeness rather than trust.
 */
describe('message catalog', () => {
  it('carries every locale for every key', () => {
    for (const [key, byLocale] of Object.entries(MESSAGES)) {
      for (const locale of LOCALES) {
        expect(byLocale[locale], `${key} → ${locale}`).toBeTruthy()
      }
    }
  })

  it('falls back to Arabic for an unsupported locale instead of rendering a key', () => {
    expect(message('fatal.retry', 'de-DE')).toBe(message('fatal.retry', 'ar'))
    expect(message('fatal.retry', 'ar')).toContain('إعادة المحاولة')
  })

  it('never renders a raw key at the edge', () => {
    expect(message('does.not.exist' as 'fatal.retry', 'ar')).not.toBe('does.not.exist')
  })

  it('resolves a regional tag to its language', () => {
    expect(message('fatal.retry', 'ar-EG')).toBe(message('fatal.retry', 'ar'))
  })
})

describe('directionOf', () => {
  it('is rtl for Arabic and ltr for Latin-script locales', () => {
    expect(directionOf('ar')).toBe('rtl')
    expect(directionOf('ar-EG')).toBe('rtl')
    expect(directionOf('en-US')).toBe('ltr')
    expect(directionOf('fr')).toBe('ltr')
  })

  it('defaults a locale it cannot classify to rtl, because that is the product default', () => {
    expect(directionOf('')).toBe('rtl')
  })
})
