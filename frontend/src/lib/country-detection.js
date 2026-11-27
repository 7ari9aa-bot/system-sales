/**
 * Which market is this visitor in?
 *
 * The site used to answer this by ASKING — a full page at `/` that listed the
 * countries before anyone could see the product. That is backwards: the answer
 * is a property of the request, not a question for the customer.
 *
 * The edge already knows (Vercel sets `x-vercel-ip-country`, which the backend
 * exposes at `/public/geo`), so detection is one small call cached for the
 * session, with the live market as the fallback whenever the answer is unknown
 * or the country is not launched yet. A visitor can still override it from the
 * header switcher; that choice wins for the session.
 */
import { apiUrl } from '@/lib/api';
import { DEFAULT_COUNTRY_SLUG, isCountryLive } from '@/lib/markets';

const CACHE_KEY = 'fihrist:country';
/** Long enough for one same-origin call, short enough not to delay a page. */
const TIMEOUT_MS = 600;

function readCache() {
  try {
    const value = window.sessionStorage.getItem(CACHE_KEY);
    return value && isCountryLive(value) ? value : null;
  } catch {
    return null;
  }
}

function writeCache(slug) {
  try {
    window.sessionStorage.setItem(CACHE_KEY, slug);
  } catch {
    /* private mode: detection just runs again next visit */
  }
}

export function rememberCountry(slug) {
  if (slug && isCountryLive(slug)) writeCache(slug);
}

async function fetchCountryCode() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(apiUrl('/public/geo'), {
      signal: controller.signal,
      headers: { accept: 'application/json' },
    });
    if (!response.ok) return null;
    const body = await response.json();
    return typeof body?.country === 'string' ? body.country.toLowerCase() : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * The market slug this visitor should land on: their own when it is live,
 * otherwise the live default. Never throws, never blocks longer than TIMEOUT_MS.
 */
export async function detectCountrySlug() {
  const cached = readCache();
  if (cached) return cached;
  const detected = await fetchCountryCode();
  const slug = detected && isCountryLive(detected) ? detected : DEFAULT_COUNTRY_SLUG;
  writeCache(slug);
  return slug;
}
