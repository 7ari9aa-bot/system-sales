// Build internal links for the active country and language. Public marketing pages live at
// `/{country}/{lang}/...`; anything that is not a public marketing path (login, register,
// dashboard) is left untouched because those screens are not localized by URL.
//
// The country matters: a visitor on /sa/en/pricing must stay in Saudi Arabia (its prices, its
// VAT) when they follow a link or switch language, not be sent to the Egyptian site.

import { COUNTRY_SLUGS, DEFAULT_COUNTRY, buildLocalizedRoute } from './public-seo-routes.mjs'

const LOCALIZED_FIRST_SEGMENTS = new Set([
  '', 'product', 'conversations', 'context', 'assistant', 'automation', 'pricing',
  'security', 'privacy', 'terms', 'data-deletion', 'contact-sales', 'support', 'solutions', 'blog',
])

const ALREADY_PREFIXED = new RegExp(`^/(${COUNTRY_SLUGS.join('|')})(/|$)`)

/**
 * The address of a public page in `locale` for `country`. Links that already carry a country
 * prefix, and every non-marketing path, come back unchanged.
 */
export function localizePath(path, locale, country = DEFAULT_COUNTRY) {
  if (typeof path !== 'string' || !path.startsWith('/')) return path
  const [pathname, rest = ''] = path.split(/([?#].*)/)
  if (ALREADY_PREFIXED.test(pathname)) return path
  // An old English address keeps its meaning: /en/pricing is the English pricing page.
  let base = pathname
  let lang = locale
  if (pathname === '/en' || pathname.startsWith('/en/')) {
    base = pathname === '/en' ? '/' : pathname.slice(3)
    lang = 'en'
  }
  const first = base.split('/')[1] ?? ''
  if (!LOCALIZED_FIRST_SEGMENTS.has(first)) return path
  return `${buildLocalizedRoute(country, lang, base)}${rest}`
}

/** Rewrite internal <a href> values inside a DOM subtree so pages link to their own country and language. */
export function localizeHtmlLinks(root, locale, country = DEFAULT_COUNTRY) {
  if (!root) return
  root.querySelectorAll('a[href^="/"]').forEach((anchor) => {
    const href = anchor.getAttribute('href')
    const next = localizePath(href, locale, country)
    if (next !== href) anchor.setAttribute('href', next)
  })
}

/** Same rewrite for an HTML string (used when prerendering the public pages). */
export function localizeHtmlString(html, locale, country = DEFAULT_COUNTRY) {
  return html.replace(/(<a\b[^>]*?\shref=")(\/[^"]*)(")/g, (_m, pre, href, post) => `${pre}${localizePath(href, locale, country)}${post}`)
}
