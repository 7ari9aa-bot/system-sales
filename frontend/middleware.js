/**
 * The root is a redirect, not a page.
 *
 * `/` used to be a country picker, then a client-side redirect that painted a
 * "taking you to your market" screen while the real page loaded — the URL said
 * /eg/ar while the redirect screen was still on screen. Both are the same
 * mistake: making the visitor wait for something the request already knows.
 *
 * The edge knows the country (Vercel sets `x-vercel-ip-country`) and can answer
 * before any HTML is sent, so `/` is a 307 to the visitor's market. Egypt is the
 * only live market, so everything else lands there until a market launches —
 * adding one is one line in LIVE_MARKETS.
 */
const LIVE_MARKETS = new Set(['EG']);
const DEFAULT_MARKET = 'eg';
const DEFAULT_LOCALE = 'ar';

export const config = { matcher: '/' };

export function middleware(request) {
  const detected = (request.headers.get('x-vercel-ip-country') || '').toUpperCase();
  const market = LIVE_MARKETS.has(detected) ? detected.toLowerCase() : DEFAULT_MARKET;
  const url = new URL(request.url);
  return Response.redirect(new URL(`/${market}/${DEFAULT_LOCALE}`, url), 307);
}
