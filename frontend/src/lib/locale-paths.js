// Build internal links for the active locale. English pages live under /en.
// Anything that is not a public marketing path (login, register, dashboard)
// is left untouched because those screens are not localized by URL.

const LOCALIZED_FIRST_SEGMENTS = new Set([
  '', 'product', 'conversations', 'context', 'assistant', 'automation', 'pricing',
  'security', 'privacy', 'terms', 'contact-sales', 'support', 'solutions',
])

export function localizePath(path, locale) {
  if (locale !== 'en' || typeof path !== 'string' || !path.startsWith('/')) return path
  if (path === '/en' || path.startsWith('/en/')) return path
  const [pathname, rest = ''] = path.split(/([?#].*)/)
  const first = pathname.split('/')[1] ?? ''
  if (!LOCALIZED_FIRST_SEGMENTS.has(first)) return path
  const base = pathname === '/' ? '/en' : `/en${pathname}`
  return `${base}${rest}`
}

/** Rewrite internal <a href> values inside a DOM subtree so English pages link to English pages. */
export function localizeHtmlLinks(root, locale) {
  if (!root || locale !== 'en') return
  root.querySelectorAll('a[href^="/"]').forEach((anchor) => {
    const href = anchor.getAttribute('href')
    const next = localizePath(href, locale)
    if (next !== href) anchor.setAttribute('href', next)
  })
}

/** Same rewrite for an HTML string (used when prerendering /en/* pages). */
export function localizeHtmlString(html, locale) {
  if (locale !== 'en') return html
  return html.replace(/(<a\b[^>]*?\shref=")(\/[^"]*)(")/g, (_m, pre, href, post) => `${pre}${localizePath(href, locale)}${post}`)
}
