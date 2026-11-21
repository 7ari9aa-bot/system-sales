// @vitest-environment node
// What Meta's app review reads: a privacy policy that names Facebook data, terms that are not a
// placeholder, and a public data-deletion page. Each assertion below failed before the pages existed.
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import Privacy from './Privacy'
import Terms from './Terms'
import DataDeletion from './DataDeletion'
import { PUBLIC_SEO_ROUTES, resolveLocalizedPath } from '@/lib/public-seo-routes.mjs'
import { pageMeta, pageDescription } from '@/pages/Fihrist'

const html = (El, locale) => renderToStaticMarkup(<El locale={locale} />)

describe('data deletion page', () => {
  it('is a registered public route in both live countries and both languages', () => {
    expect(PUBLIC_SEO_ROUTES.map((r) => r.path)).toContain('/data-deletion')
    for (const p of ['/eg/ar/data-deletion', '/eg/en/data-deletion', '/sa/ar/data-deletion', '/sa/en/data-deletion']) {
      expect(resolveLocalizedPath(p)).toMatchObject({ basePath: '/data-deletion', isLive: true })
    }
  })

  it('has a title and description for search and for Meta', () => {
    expect(pageMeta['data-deletion'].en).toMatch(/delet/i)
    expect(pageDescription['data-deletion'].ar.length).toBeGreaterThan(30)
  })

  it('tells a person how to remove their Facebook data, in both languages', () => {
    const en = html(DataDeletion, 'en')
    expect(en).toMatch(/Facebook/)
    expect(en).toMatch(/Apps and Websites/i)
    expect(en).toMatch(/confirmation code/i)
    const ar = html(DataDeletion, 'ar')
    expect(ar).toMatch(/فيسبوك/)
    expect(ar).toMatch(/رمز التأكيد/)
  })

  it('states the real retention period from the lifecycle service (30 days), not a vague promise', () => {
    expect(html(DataDeletion, 'en')).toMatch(/30 days/)
    expect(html(DataDeletion, 'ar')).toMatch(/30 يومًا/)
  })
})

describe('privacy policy and terms are fit to show Meta', () => {
  it('privacy names Facebook data, what is read and that deletion has its own page', () => {
    const en = html(Privacy, 'en')
    expect(en).toMatch(/Facebook/)
    expect(en).toMatch(/Page/)
    expect(en).toMatch(/href="\/data-deletion"/)
  })

  it('neither page still calls itself an illustrative draft', () => {
    for (const El of [Privacy, Terms]) {
      for (const locale of ['ar', 'en']) {
        const out = html(El, locale)
        expect(out).not.toMatch(/illustrative/i)
        expect(out).not.toMatch(/توضيحي/)
        expect(out).not.toMatch(/structure testing/i)
      }
    }
  })
})

// The production build (scripts/prerender-public-pages.mjs) refuses any page whose title is not
// 30-60 characters or whose description is not 50-160. The first deploy of /data-deletion failed
// on exactly this, so the same limits are checked here, before Vercel.
describe('data deletion SEO copy fits the prerender limits', () => {
  for (const locale of ['ar', 'en']) {
    it(`title and description lengths (${locale})`, () => {
      const t = pageMeta['data-deletion'][locale]
      const d = pageDescription['data-deletion'][locale]
      expect(t.length).toBeGreaterThanOrEqual(30)
      expect(t.length).toBeLessThanOrEqual(60)
      expect(d.length).toBeGreaterThanOrEqual(50)
      expect(d.length).toBeLessThanOrEqual(160)
    })
  }
})
