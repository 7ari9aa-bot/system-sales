import { afterEach, describe, expect, it } from 'vitest'

import { applyDocumentLocale, pickLocale } from '@/app/document'

describe('pickLocale', () => {
  it('keeps a language the app has copy for', () => {
    expect(pickLocale('en-US')).toBe('en')
    expect(pickLocale('ar-EG')).toBe('ar')
  })

  it('falls back to Arabic, the product default, for anything else', () => {
    expect(pickLocale('de-DE')).toBe('ar')
    expect(pickLocale('')).toBe('ar')
  })
})

describe('applyDocumentLocale', () => {
  afterEach(() => {
    document.documentElement.removeAttribute('lang')
    document.documentElement.removeAttribute('dir')
  })

  it('writes the locale and its direction onto the document element', () => {
    applyDocumentLocale('ar-EG')

    expect(document.documentElement.lang).toBe('ar-EG')
    expect(document.documentElement.dir).toBe('rtl')
  })

  it('flips the whole tree for a Latin-script locale', () => {
    applyDocumentLocale('en-US')

    expect(document.documentElement.lang).toBe('en-US')
    expect(document.documentElement.dir).toBe('ltr')
  })

  it('leaves an unusable locale at the Arabic default rather than clearing the attributes', () => {
    applyDocumentLocale('   ')

    expect(document.documentElement.lang).toBe('ar')
    expect(document.documentElement.dir).toBe('rtl')
  })
})
