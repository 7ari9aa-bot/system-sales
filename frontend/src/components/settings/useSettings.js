/** Shared settings hook — the single source for effective settings consumption.
 *
 * Fetches ALL effective settings and their definitions from the unified
 * `/settings/effective` and `/settings/definitions` endpoints, groups them
 * by domain (as the registry defines), and exposes a save function.
 *
 * Every settings screen that wants to consume the unified endpoint should
 * use this hook instead of making its own scattered calls. This is the P3
 * goal described in docs/settings/frontend-specification.md.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";

export function useSettings(opts = {}) {
  const { domain, keys, segment } = opts;

  const [defs, setDefs] = useState(null);
  const [values, setValues] = useState({});
  const [original, setOriginal] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");

  // Build the query strings for definitions and effective.
  const defsQuery = useMemo(() => {
    const params = new URLSearchParams();
    if (domain) params.set("domain", domain);
    if (segment) params.set("segment", segment);
    const s = params.toString();
    return s ? `?${s}` : "";
  }, [domain, segment]);

  const effQuery = useMemo(() => {
    const params = new URLSearchParams();
    params.set("scope", "tenant");
    if (domain) params.set("domain", domain);
    if (keys) params.set("keys", keys);
    const s = params.toString();
    return s ? `?${s}` : "";
  }, [domain, keys]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");

    Promise.all([
      api(`/settings/definitions${defsQuery}`),
      api(`/settings/effective${effQuery}`),
    ])
      .then(([defList, eff]) => {
        if (!alive) return;
        const list = Array.isArray(defList) ? defList : [];
        setDefs(list);
        const v = {};
        for (const [key, resolved] of Object.entries(eff || {})) {
          v[key] = resolved.value;
        }
        setValues(v);
        setOriginal(v);
        setLoading(false);
      })
      .catch((err) => {
        if (!alive) return;
        setError(err?.message || "Could not load settings");
        setLoading(false);
      });
    return () => { alive = false; };
  }, [defsQuery, effQuery]);

  const dirty = useMemo(
    () => JSON.stringify(values) !== JSON.stringify(original),
    [values, original],
  );

  // Group definitions by domain — the registry domain is the grouping key.
  const grouped = useMemo(() => {
    if (!defs) return {};
    const map = {};
    for (const d of defs) {
      if (!map[d.domain]) map[d.domain] = [];
      map[d.domain].push(d);
    }
    // Sort keys within each domain for stable display.
    for (const dom of Object.keys(map)) {
      map[dom].sort((a, b) => a.key.localeCompare(b.key));
    }
    return map;
  }, [defs]);

  const setValue = useCallback((key, value) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  }, []);

  const save = useCallback(async () => {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const changes = {};
      for (const [k, v] of Object.entries(values)) {
        if (v !== original[k]) changes[k] = v;
      }
      if (Object.keys(changes).length > 0) {
        await api("/settings/bulk", {
          method: "POST",
          body: { scope: "tenant", settings: changes },
        });
      }
      setOriginal({ ...values });
      setNotice("saved");
    } catch (err) {
      setError(err?.message || "Could not save");
    } finally {
      setSaving(false);
    }
  }, [values, original]);

  const reset = useCallback(() => {
    setValues({ ...original });
  }, [original]);

  return {
    defs,
    grouped,
    values,
    original,
    dirty,
    loading,
    error,
    saving,
    notice,
    setValue,
    save,
    reset,
  };
}
