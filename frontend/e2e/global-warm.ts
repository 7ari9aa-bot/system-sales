/* Warm every route the suite visits before any spec runs.
 *
 * Locally the server is `next dev`, which compiles each route on first hit.
 * Under parallel workers that first hit easily exceeds the 5s assertion
 * timeout, so cold-navigation tests (the auth redirect chain, the post-login
 * push to /inbox) flake. A plain GET forces each compile once, serially.
 * On CI the server is the production build, so this is just cheap requests. */

const ROUTES = [
  "/auth/login",
  "/login",
  "/dashboard",
  "/inbox",
  "/orders",
  "/marketing",
  "/notifications",
  "/my-work",
];

const BASE = process.env.BASE_URL ?? "http://127.0.0.1:3000";

export default async function globalWarm() {
  // The server may still be booting when this runs — poll until it answers.
  const deadline = Date.now() + 120_000;
  for (;;) {
    try {
      const res = await fetch(BASE, { signal: AbortSignal.timeout(5_000) });
      if (res.status < 500) break;
    } catch {
      /* not up yet */
    }
    if (Date.now() > deadline) throw new Error(`dev server never answered at ${BASE}`);
    await new Promise((r) => setTimeout(r, 1_000));
  }

  // Compile every route the suite navigates to, once.
  await Promise.all(
    ROUTES.map(async (route) => {
      const res = await fetch(`${BASE}${route}`, {
        redirect: "follow",
        signal: AbortSignal.timeout(120_000),
      });
      if (!res.ok) throw new Error(`warm-up of ${route} failed: HTTP ${res.status}`);
    }),
  );
}
