export type RuntimeConfigResult =
  | { readonly ok: true; readonly apiBaseUrl: string }
  | { readonly ok: false; readonly reason: 'missing' | 'invalid' | 'insecure' }

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1'])

/**
 * The one gate a base URL passes on its way into the app. There is no default
 * host anywhere in this codebase on purpose: a build that shipped a host would
 * be a client that cannot be pointed at another environment without a rebuild.
 */
export function parseRuntimeConfig(raw: string | null | undefined): RuntimeConfigResult {
  const value = raw?.trim() ?? ''

  if (!value) return { ok: false, reason: 'missing' }

  let url: URL
  try {
    url = new URL(value)
  } catch {
    return { ok: false, reason: 'invalid' }
  }

  const secure = url.protocol === 'https:'
  const plain = url.protocol === 'http:'

  if (!secure && !plain) return { ok: false, reason: 'invalid' }
  if (!url.hostname) return { ok: false, reason: 'invalid' }
  if (url.username || url.password) return { ok: false, reason: 'invalid' }
  if (url.search) return { ok: false, reason: 'invalid' }
  if (!secure && !LOOPBACK_HOSTS.has(stripBracket(url.hostname))) return { ok: false, reason: 'insecure' }

  const path = url.pathname.replace(/\/$/, '')

  return { ok: true, apiBaseUrl: `${url.origin}${path}` }
}

function stripBracket(host: string): string {
  return host.startsWith('[') && host.endsWith(']') ? host.slice(1, -1) : host
}
