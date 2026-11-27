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

async function fetchJson(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      headers: { accept: 'application/json' },
    });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Two sources, cheapest first.
 *
 * 1. Our own `/public/geo`, which reads the edge's country header. It is the
 *    only source that never leaves our stack — but Vercel does not forward the
 *    geo header through this project's API rewrite, so today it answers null.
 * 2. A keyless public lookup by IP, used only when (1) has nothing to say.
 *    That means one third-party request per session at most, and none at all
 *    once the answer is cached.
 */
async function fetchCountryCode() {
  const own = await fetchJson(apiUrl('/public/geo'));
  if (typeof own?.country === 'string' && own.country.length === 2) {
    return own.country.toLowerCase();
  }
  const who = await fetchJson('https://ipwho.is/');
  const code = who?.country_code;
  return typeof code === 'string' && code.length === 2 ? code.toLowerCase() : null;
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
