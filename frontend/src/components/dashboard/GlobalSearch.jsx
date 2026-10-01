import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search, Users, ShoppingBag, Package, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const ENTITY_ICONS = { customer: Users, order: ShoppingBag, product: Package };

const HREF_BY_TYPE = {
  customer: "/customers",
  order: "/orders",
  product: "/products",
};

/** البحث الشامل — بحث الـbackend الحقيقي (GET /search) بدل البحث
 *  المحلي في نسخ الكيانات. النتيجة بتفتح الشاشة المناسبة. */
export default function GlobalSearch({ autoFocus, className, onPick }) {
  const t = useT();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [hits, setHits] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const wrapRef = useRef(null);
  const seqRef = useRef(0);

  useEffect(() => {
    function handler(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    const term = q.trim();
    const seq = ++seqRef.current;
    if (term.length < 2) {
      setHits(null);
      setBusy(false);
      setError("");
      return;
    }
    setBusy(true);
    setHits(null);
    setError("");
    const id = window.setTimeout(() => {
      api(`/search?q=${encodeURIComponent(term)}&limit=8`)
        .then((rows) => {
          if (seqRef.current === seq) setHits(Array.isArray(rows) ? rows : []);
        })
        .catch((requestError) => {
          if (seqRef.current !== seq) return;
          setHits([]);
          setError(requestError?.message || t("search.loadError", "Could not search right now."));
        })
        .finally(() => {
          if (seqRef.current === seq) setBusy(false);
        });
    }, 250);
    return () => window.clearTimeout(id);
  }, [q, attempt, t]);

  const flat = useMemo(() => hits ?? [], [hits]);

  function pick(item) {
    navigate(HREF_BY_TYPE[item.entity_type] ?? "/dashboard");
    setOpen(false);
    setQ("");
    setActive(0);
    onPick?.();
  }

  function onKey(e) {
    if (!open || flat.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (a + 1) % flat.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a - 1 + flat.length) % flat.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      pick(flat[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className={cn("relative", className)} ref={wrapRef}>
      <div className="flex h-9 items-center gap-2 rounded-lg border border-border bg-surface px-3 text-muted-foreground focus-within:border-primary/50">
        <Search className="h-4 w-4 shrink-0" />
        <input
          value={q}
          autoFocus={autoFocus}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
            setActive(0);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKey}
          placeholder={t("header.search")}
          aria-label={t("header.search")}
          className="h-full min-w-0 flex-1 bg-transparent text-[13px] text-foreground outline-none placeholder:text-muted-foreground"
        />
        {busy && <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />}
      </div>

      {open && q.trim().length >= 2 && (
        <div className="absolute inset-x-0 top-full z-50 mt-2 max-h-80 overflow-y-auto rounded-xl border border-border bg-popover p-1.5 shadow-lg animate-fade-in scrollbar-thin">
          {error ? (
            <div className="px-2.5 py-3 text-[12.5px] text-destructive" role="alert">
              <span>{error}</span>
              <button
                type="button"
                onClick={() => setAttempt((value) => value + 1)}
                className="ml-2 text-primary hover:underline"
              >
                {t("common.retry", "Retry")}
              </button>
            </div>
          ) : flat.length === 0 ? (
            <div className="px-2.5 py-3 text-[12.5px] text-muted-foreground">
              {busy ? t("common.loading") : t("search.noResults")}
            </div>
          ) : (
            flat.map((hit, i) => {
              const Icon = ENTITY_ICONS[hit.entity_type] || Search;
              return (
                <button
                  key={`${hit.entity_type}-${hit.entity_id}`}
                  type="button"
                  onClick={() => pick(hit)}
                  onMouseEnter={() => setActive(i)}
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-start",
                    i === active ? "bg-surface" : "",
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12.5px] font-medium">{hit.title}</span>
                    {hit.snippet && (
                      <span className="block truncate text-[11.5px] text-muted-foreground">{hit.snippet}</span>
                    )}
                  </span>
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
