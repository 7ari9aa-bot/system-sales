import { DEFAULT_LOCALE, LOCALES, directionOf, type Locale } from '@/shared/i18n'

/**
 * The address bar of the whole UI. Everything that renders direction reads it
 * from here, so no component gets to decide for itself that it is LTR.
 */
export function applyDocumentLocale(locale: string): void {
  const value = locale.trim() === '' ? DEFAULT_LOCALE : locale.trim()

  document.documentElement.lang = value
  document.documentElement.dir = directionOf(value)
}

/** Narrows a runtime preference to a language this build carries copy for. */
export function pickLocale(preferred: string): Locale {
  const base = preferred.trim().toLowerCase().split(/[-_]/)[0] ?? ''

  return (LOCALES as readonly string[]).includes(base) ? (base as Locale) : DEFAULT_LOCALE
}
