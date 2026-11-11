import React, { useEffect, useRef } from "react";

/**
 * Cloudflare Turnstile widget.
 *
 * Renders nothing when VITE_TURNSTILE_SITE_KEY is unset, so the screens work
 * exactly as before until the keys exist. The site key is public by design;
 * the secret lives only on the server.
 *
 * `onToken(token)` fires with a fresh single-use token, `onToken(null)` when it
 * expires or errors. Bump `resetKey` after a failed submit: a token is spent by
 * the attempt, so the widget must hand out a new one.
 */
export const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY || "";
export const turnstileEnabled = () => Boolean(TURNSTILE_SITE_KEY);

const SCRIPT_SRC = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
let scriptPromise = null;

function loadScript() {
  if (typeof window === "undefined") return Promise.reject(new Error("no window"));
  if (window.turnstile) return Promise.resolve(window.turnstile);
  if (!scriptPromise) {
    scriptPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = SCRIPT_SRC;
      s.async = true;
      s.defer = true;
      s.onload = () => resolve(window.turnstile);
      s.onerror = () => {
        scriptPromise = null; // allow a retry after a blocked/failed load
        reject(new Error("turnstile script failed"));
      };
      document.head.appendChild(s);
    });
  }
  return scriptPromise;
}

export default function Turnstile({ onToken, resetKey = 0, theme = "auto", action }) {
  const box = useRef(null);
  const widgetId = useRef(null);
  const cb = useRef(onToken);
  cb.current = onToken;

  useEffect(() => {
    if (!TURNSTILE_SITE_KEY) return undefined;
    let cancelled = false;
    loadScript()
      .then((ts) => {
        if (cancelled || !box.current) return;
        widgetId.current = ts.render(box.current, {
          sitekey: TURNSTILE_SITE_KEY,
          theme,
          action,
          callback: (t) => cb.current?.(t),
          "expired-callback": () => cb.current?.(null),
          "error-callback": () => cb.current?.(null),
        });
      })
      .catch(() => cb.current?.(null));
    return () => {
      cancelled = true;
      if (widgetId.current != null && window.turnstile) {
        try {
          window.turnstile.remove(widgetId.current);
        } catch {
          /* widget already gone */
        }
      }
      widgetId.current = null;
    };
  }, [theme, action]);

  useEffect(() => {
    if (resetKey && widgetId.current != null && window.turnstile) {
      cb.current?.(null);
      try {
        window.turnstile.reset(widgetId.current);
      } catch {
        /* not rendered yet */
      }
    }
  }, [resetKey]);

  if (!TURNSTILE_SITE_KEY) return null;
  return <div ref={box} data-testid="turnstile" className="flex justify-center" />;
}
