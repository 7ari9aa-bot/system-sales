import React from "react";
import { api } from "@/lib/api";

/** The account workspace, fetched once per section.
 *
 * Every workspace section needs the same object (name, role, region, size), so it is
 * read here rather than five times. A failure is kept as a message instead of being
 * swallowed: a page that renders "—" everywhere reads like an empty workspace, and an
 * empty workspace is a very different thing from an unreachable one.
 */
export default function useWorkspace() {
  const [state, setState] = React.useState({ data: null, error: "", loading: true });

  const reload = React.useCallback(async () => {
    setState((current) => ({ ...current, loading: true, error: "" }));
    try {
      const data = await api("/workspaces/current");
      setState({ data, error: "", loading: false });
      return data;
    } catch (failure) {
      setState({ data: null, error: failure?.message || "failed", loading: false });
      return null;
    }
  }, []);

  React.useEffect(() => {
    let alive = true;
    api("/workspaces/current")
      .then((data) => {
        if (alive) setState({ data, error: "", loading: false });
      })
      .catch((failure) => {
        if (alive) setState({ data: null, error: failure?.message || "failed", loading: false });
      });
    return () => {
      alive = false;
    };
  }, []);

  return { ...state, reload };
}
