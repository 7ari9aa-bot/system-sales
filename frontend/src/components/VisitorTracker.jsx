import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { apiUrl } from "@/lib/api";
import { VISITOR_KEY, SESSION_KEY, getOrCreate } from "@/lib/visitorId";

function send(event) {
  const payload = JSON.stringify(event);
  try {
    fetch(apiUrl("/public/telemetry"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
      keepalive: true,
      credentials: "omit",
    }).catch(() => {});
  } catch {
    // Telemetry must never break the page.
  }
}

export default function VisitorTracker() {
  const location = useLocation();

  useEffect(() => {
    const visitorId = getOrCreate(localStorage, VISITOR_KEY);
    const sessionId = getOrCreate(sessionStorage, SESSION_KEY);
    // PATHNAME ONLY — no query string. Auth routes receive links like
    // /register?email=... and /reset?token=...; persisting location.search
    // would store personal data and secret tokens in plaintext telemetry
    // (deep review round 3, M1). href is derived from the same clean path.
    const path = location.pathname;
    const base = {
      visitor_id: visitorId,
      session_id: sessionId,
      path,
      url: `${window.location.origin}${path}`,
      referrer: document.referrer ? new URL(document.referrer, window.location.origin).pathname : null,
    };

    send({ ...base, event_type: "page_view" });

    const onLoad = () => {
      const nav = performance.getEntriesByType?.("navigation")?.[0];
      if (nav) {
        send({
          ...base,
          event_type: "performance",
          duration_ms: Math.max(0, Math.round(nav.duration || 0)),
          metadata: {
            dom_content_loaded_ms: Math.round(nav.domContentLoadedEventEnd || 0),
            load_event_ms: Math.round(nav.loadEventEnd || 0),
          },
        });
      }
    };
    if (document.readyState === "complete") onLoad();
    else window.addEventListener("load", onLoad, { once: true });

    // Frustration signal (Clarity/FullStory pattern): 3+ clicks on the SAME
    // element within 1.5s is a RAGE CLICK — the strongest early UX-breakage
    // signal users never report. One event per incident, not per click.
    let rage = { key: null, count: 0, first: 0, sent: false };
    const onClick = (event) => {
      const element = event.target?.closest?.("a,button,[data-track]");
      if (!element) return;
      const now = Date.now();
      const key = `${element.tagName}:${element.getAttribute("data-track") || element.getAttribute("aria-label") || ""}`;
      if (key === rage.key && now - rage.first < 1500) {
        rage.count += 1;
      } else {
        rage = { key, count: 1, first: now, sent: false };
      }
      const label = (
        element.getAttribute("data-track") ||
        element.getAttribute("aria-label") ||
        element.innerText ||
        element.textContent ||
        ""
      ).trim().slice(0, 160);
      if (rage.count >= 3 && !rage.sent) {
        rage.sent = true;
        send({
          ...base,
          event_type: "rage_click",
          element: label || element.tagName.toLowerCase(),
          metadata: {
            clicks: rage.count,
            window_ms: now - rage.first,
          },
        });
        return;
      }
      send({
        ...base,
        event_type: "click",
        element: label || element.tagName.toLowerCase(),
        metadata: {
          tag: element.tagName.toLowerCase(),
          href: element.getAttribute("href") || undefined,
        },
      });
    };

    const onError = (event) => {
      send({
        ...base,
        event_type: "error",
        element: event.message?.slice(0, 500) || "window.error",
        metadata: {
          source: event.filename || undefined,
          line: event.lineno || undefined,
          column: event.colno || undefined,
        },
      });
    };

    document.addEventListener("click", onClick, { capture: true });
    window.addEventListener("error", onError);
    return () => {
      document.removeEventListener("click", onClick, { capture: true });
      window.removeEventListener("error", onError);
      window.removeEventListener("load", onLoad);
    };
  }, [location.pathname, location.search]);

  return null;
}
