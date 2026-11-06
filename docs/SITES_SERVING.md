# SITES_SERVING.md — serving customer websites (subdomain phase)

How a published customer site reaches the internet, from the code that already
ships today to the DNS/TLS step that turns it on.

## What is live in code right now

- Publishing writes a **public read model** row in `website_published_sites`
  (no `tenant_id` column — the only table the unauthenticated surface reads).
- `GET /api/v1/...` untouched; the public site is served by the backend at
  **root** level:
  - `GET /sites/{slug}` — full HTML document for a published site (today's
    path-based serving; works with no DNS changes).
  - `GET /` — **Host mode**: when the request host is
    `{slug}.{websites_served_domain}`, the same renderer serves that site.
    Disabled (honest 404) while `websites_served_domain` is empty, and it
    never guesses from an untrusted Host header.
- Products on the page are read live under RLS by binding the snapshot's
  server-stamped `tenant_id` (see `app/modules/website/services/public_service.py`).

## Turning on subdomains (operator runbook)

1. Pick the public suffix, e.g. `sites.example.com`.
2. DNS: one wildcard A/CNAME record `*.sites.example.com` → the backend
   service (Railway). A wildcard record covers every customer slug; no
   per-customer DNS step, ever.
3. TLS: a wildcard certificate for `*.sites.example.com`. Easiest path is
   Cloudflare in front (proxy + free wildcard edge cert, origin cert for the
   backend); Railway also accepts custom domains but wildcard cert issuance
   there is limited — Cloudflare is the recommended route.
4. Set the backend env `WEBSITES_SERVED_DOMAIN=sites.example.com` and deploy.
   `GET /` starts resolving customer sites; `GET /sites/{slug}` keeps working
   (useful for previews and debugging).
5. Point merchants at `https://{slug}.sites.example.com`. The dashboard's
   live link already uses `/sites/{slug}`; a frontend setting can switch it
   to the subdomain form once step 4 is deployed.

## Slug rules (what a customer may claim)

Defined once in `backend/app/modules/website/slugs.py`:

- 3–80 chars, `a-z 0-9 -`, starts/ends alphanumeric.
- Never a reserved name (`www`, `api`, `admin`, `app`, `owner`, `pay`, ... —
  full list in `RESERVED_SLUGS`).
- A slug is claimed by an open/activated purchase and freed when that
  purchase is rejected or cancelled; uniqueness spans `websites` +
  `website_purchases` and is serialized per-slug with a
  `pg_advisory_xact_lock` + the `website_slug_taken` SECURITY DEFINER.
- Arabic site names are slugified by dropping non-ASCII (transliteration is
  deferred, same as the spec's seo.py); the merchant can always type the
  address explicitly.

## Adding custom domains later

`website_published_sites.hostname` (unique where not null) is the ready slot:
a verified custom hostname goes there, and Host-mode resolution already tries
the hostname before the slug. The domain-verification lifecycle (DNS challenge
→ verified → active) is the next slice — the spec's `domains.py` state machine
is the reference.
