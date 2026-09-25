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
 *  Pass `onFire` for a create surface that is not a dialog (the settings page
 *  focuses its invite field instead of opening one); its return is then unused. */
export function useCreateDialog(
  onFire?: () => void,
): [boolean, React.Dispatch<React.SetStateAction<boolean>>] {
  const [open, setOpen] = React.useState(false);
  const router = useRouter();

  const fire = React.useRef(onFire);
  React.useEffect(() => {
    fire.current = onFire;
  }, [onFire]);

  React.useEffect(() => {
    const url = new URL(window.location.href);
    if (url.searchParams.get(DEEP_LINK_PARAM) !== DEEP_LINK_VALUE) return;
    setOpen(true);
    fire.current?.();
    url.searchParams.delete(DEEP_LINK_PARAM);
    const qs = url.searchParams.toString();
    router.replace(qs ? `${url.pathname}?${qs}` : url.pathname, { scroll: false });
  }, [router]);

  return [open, setOpen];
}
