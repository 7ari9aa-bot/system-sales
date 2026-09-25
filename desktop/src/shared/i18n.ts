export const LOCALES = ['ar', 'en'] as const

export type Locale = (typeof LOCALES)[number]

export const DEFAULT_LOCALE: Locale = 'ar'

export const MESSAGES = {
  // The product name is a brand, not a translation: the web app renders "Fihrist"
  // in both locales, and a client that called it فهرس would be a second identity.
  'app.name': { ar: 'Fihrist', en: 'Fihrist' },
  'common.unknown': { ar: 'خطأ غير معروف', en: 'Unknown error' },
  'fatal.aria': { ar: 'تعذّر عرض هذا القسم', en: 'This section failed to render' },
  'fatal.title': { ar: 'تعذّر عرض هذا الجزء', en: 'This part of the app failed' },
  'fatal.body': {
    ar: 'لم يُفقد شيء من بياناتك. يمكنك إعادة المحاولة، وإن تكرّر الخطأ أرسل المعرّف أدناه إلى الدعم.',
    en: 'Nothing of yours was lost. Try again, and if it repeats send the id below to support.',
  },
  'fatal.request': { ar: 'معرّف الطلب', en: 'Request id' },
  'fatal.retry': { ar: 'إعادة المحاولة', en: 'Try again' },
  'fatal.code': { ar: 'رمز الخطأ', en: 'Error code' },
  'boot.title': { ar: 'جارٍ تجهيز Fihrist', en: 'Preparing Fihrist' },
  'boot.checking': { ar: 'جارٍ تجهيز Fihrist', en: 'Preparing Fihrist' },
  'boot.ready': { ar: 'جاهز للاتصال بالخادم', en: 'Ready to reach the server' },
  'boot.address': { ar: 'عنوان الخادم', en: 'Server address' },
  'boot.unconfigured': {
    ar: 'لم يُضبط عنوان الخادم. أضِفه في ملف الإعداد ثم أعيد التشغيل.',
    en: 'No server address is configured. Add one to the settings file and relaunch.',
  },
  'boot.invalid': {
    ar: 'عنوان الخادم المكتوب غير صالح.',
    en: 'The configured server address is not a valid URL.',
  },
  'boot.insecure': {
    ar: 'عنوان الخادم يجب أن يكون https لتُحمى جلسة الدخول.',
    en: 'The server address must use https so your session stays protected.',
  },
  'boot.nativeOnly': {
    ar: 'هذه الواجهة تعمل داخل تطبيق سطح المكتب.',
    en: 'This interface runs inside the desktop app.',
  },
} as const satisfies Record<string, Record<Locale, string>>

export type MessageKey = keyof typeof MESSAGES

const RTL_LANGUAGES = new Set(['ar', 'he', 'fa', 'ur', 'ps', 'ku', 'sd', 'yi', 'dv'])

/** Unknown keys and unsupported locales resolve to Arabic, never to a raw key. */
export function message(key: MessageKey, locale: string = DEFAULT_LOCALE): string {
  const language = baseLanguage(locale)
  const entry = (MESSAGES as Partial<Record<MessageKey, Record<Locale, string>>>)[key]

  if (!entry) return MESSAGES['common.unknown'][DEFAULT_LOCALE]
  const language_ = language as Locale
  return entry[language_] ?? entry[DEFAULT_LOCALE]
}

/**
 * The product default is RTL, so a locale we cannot classify renders right-
 * to-left rather than silently becoming an English-shaped window.
 */
export function directionOf(locale: string): 'rtl' | 'ltr' {
  const language = baseLanguage(locale)

  if (!language) return 'rtl'
  if (RTL_LANGUAGES.has(language)) return 'rtl'

  try {
    const info = (new Intl.Locale(language) as unknown as { textInfo?: { direction?: string } })
      .textInfo
    if (info?.direction === 'rtl' || info?.direction === 'ltr') return info.direction
  } catch {
    return 'rtl'
  }

  return 'ltr'
}

function baseLanguage(locale: string): string {
  return locale.trim().toLowerCase().split(/[-_]/)[0] ?? ''
}
