"use client";

/** `?new=1` deep link — the top-bar «إنشاء» menu and the command palette both
 *  land on a page with this flag to open its create surface.
 *
 *  The flag used to be read and never removed, so a refresh re-fired it: the
 *  dialog a merchant had already filled in and closed popped open again over a
 *  clean page. Consuming the link means deleting it from the URL, which is what
 *  `router.replace` does here (a bare `window.history.replaceState` would leave
 *  the flag in the App Router's own state, where it could come back).
 *
 *  Reading `window.location` inside the effect rather than through
 *  `useSearchParams()` keeps the pages that call this out of the Suspense
 *  requirement that hook imposes on a prerendered route. */

import * as React from "react";
import { useRouter } from "next/navigation";

const DEEP_LINK_PARAM = "new";
const DEEP_LINK_VALUE = "1";

/** Returns the dialog's open state, already seeded by the deep link.
 *
 *  The flag is the only thing this hook reads, so it reports the REQUEST and
 *  leaves the surface to the page. That matters for a create surface that is
 *  not a dialog: the settings page focuses its invite field, and that field is
 *  rendered only once the page's reads have settled. A hook that fired a
 *  callback here would fire it on the mount commit — before the field exists —
 *  and the focus would land on nothing, so handing back the state and letting
 *  the page act on it when its own DOM is ready is the whole design. */
export function useCreateDialog(): [
  boolean,
  React.Dispatch<React.SetStateAction<boolean>>,
] {
  const [open, setOpen] = React.useState(false);
  const router = useRouter();

  React.useEffect(() => {
    const url = new URL(window.location.href);
    if (url.searchParams.get(DEEP_LINK_PARAM) !== DEEP_LINK_VALUE) return;
    setOpen(true);
    url.searchParams.delete(DEEP_LINK_PARAM);
    const qs = url.searchParams.toString();
    router.replace(qs ? `${url.pathname}?${qs}` : url.pathname, { scroll: false });
  }, [router]);

  return [open, setOpen];
}
